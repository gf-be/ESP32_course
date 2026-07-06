"""
ESP32 MicroPython real-time 15-state simplified ESKF.

Install this file to ESP32 as /main.py for a real-time demo.

State definition used in the report:
  error state dx = [dp(3), dv(3), dtheta(3), dbg(3), dba(3)]^T
  nominal state  = [p(3), v(3), q(4), bg(3), ba(3)]

Runtime data sources:
  - MPU6050/MPU6500-compatible IMU on I2C address 0x68
  - HMC5883L magnetometer on I2C address 0x1E
  - GPS6MV2/NEO-6M NMEA on UART2 RX=GPIO16 TX=GPIO17

Serial output:
  Lines beginning with ESKF15 are CSV records. Use
  pc_eskf_15d_realtime_capture.py on the computer to save them.
"""

from machine import Pin, I2C, UART
import math
import struct
import time


SDA_PIN = 21
SCL_PIN = 22
I2C_FREQ = 400000
MPU_ADDR = 0x68
MAG_ADDR = 0x1E

GPS_UART_ID = 2
GPS_RX_PIN = 16
GPS_TX_PIN = 17
GPS_BAUDRATE = 9600

STATUS_LED_PIN = 2
LED_ON_VALUE = 1

TARGET_HZ = 100
PRINT_HZ = 5
G = 9.80665

# Conservative use of accelerometer prediction. The attitude still updates at
# IMU rate; GPS remains the main absolute position observation.
ACCEL_NAV_GAIN = 0.20
VELOCITY_DAMPING = 0.025
MAX_NAV_ACCEL = 4.0
MAX_SPEED_MPS = 12.0

QUALITY_MIN_SATS = 4
QUALITY_MAX_HDOP = 5.0

# Static/low-speed walking constraints. When the IMU indicates the board is
# stationary, zero-velocity and weak position-hold pseudo observations keep GPS
# jitter from being interpreted as real walking motion.
STATIONARY_ACC_NORM_THR_G = 0.08
STATIONARY_GYRO_NORM_THR_DPS = 3.0
STATIONARY_COUNT_MIN = 60
STATIONARY_UPDATE_MS = 100
STATIC_GPS_SIGMA_SCALE = 5.0
ZUPT_SIGMA_MPS = 0.04
POS_HOLD_SIGMA_M = 0.65

# Accelerometer 12-parameter affine calibration.
# calibrated = C * raw + d, from accel_6pos_12param_inverse.csv.
ACC_C00 = 0.9936363144
ACC_C01 = 0.0798200426
ACC_C02 = 0.0766064259
ACC_D0 = -0.0114873061
ACC_C10 = -0.0698260446
ACC_C11 = 0.9977966301
ACC_C12 = 0.0003414386
ACC_D1 = -0.0080361168
ACC_C20 = -0.0536159808
ACC_C21 = 0.0015940015
ACC_C22 = 0.9789750285
ACC_D2 = -0.0045358955

# From gyro Allan variance experiment.
GYRO_BIAS_X = 0.228303741
GYRO_BIAS_Y = 0.964654373
GYRO_BIAS_Z = -0.100939275

# From magnetometer ellipsoid calibration.
MAG_BIAS_X = 77.082135
MAG_BIAS_Y = -94.427834
MAG_BIAS_Z = -36.852085
MAG_M00 = 1.0102826701
MAG_M01 = 0.0065974430
MAG_M02 = -0.0096782755
MAG_M10 = 0.0065974430
MAG_M11 = 0.9756936862
MAG_M12 = -0.0109598281
MAG_M20 = -0.0096782755
MAG_M21 = -0.0109598281
MAG_M22 = 1.0154785728

MAHONY_KP = 1.2
MAHONY_KI = 0.02


def ticks_ms():
    return time.ticks_ms()


def ticks_diff(a, b):
    return time.ticks_diff(a, b)


def led_write(led, on):
    if led is not None:
        led.value(LED_ON_VALUE if on else 1 - LED_ON_VALUE)


def update_led(led, mode, now, t0):
    # 0 waiting/no GPS, 1 GPS seen but no usable fix, 2 ESKF updating.
    phase = ticks_diff(now, t0)
    if mode <= 0:
        led_write(led, phase % 3000 < 80)
    elif mode == 1:
        led_write(led, phase % 1000 < 500)
    else:
        p = phase % 2000
        led_write(led, p < 120 or 260 <= p < 380)


def inv_sqrt(x):
    if x <= 0:
        return 0.0
    return 1.0 / math.sqrt(x)


def clamp(x, lo, hi):
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def normalize3(x, y, z):
    n = inv_sqrt(x * x + y * y + z * z)
    if n == 0:
        return 0.0, 0.0, 0.0
    return x * n, y * n, z * n


def quat_mul(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    )


def quat_normalize(q):
    q0, q1, q2, q3 = q
    n = inv_sqrt(q0 * q0 + q1 * q1 + q2 * q2 + q3 * q3)
    if n == 0:
        return 1.0, 0.0, 0.0, 0.0
    return q0 * n, q1 * n, q2 * n, q3 * n


def small_angle_quat(dx, dy, dz):
    angle = math.sqrt(dx * dx + dy * dy + dz * dz)
    if angle < 1e-9:
        return quat_normalize((1.0, 0.5 * dx, 0.5 * dy, 0.5 * dz))
    ax = dx / angle
    ay = dy / angle
    az = dz / angle
    half = 0.5 * angle
    s = math.sin(half)
    return math.cos(half), ax * s, ay * s, az * s


def quat_from_euler(roll_deg, pitch_deg, yaw_deg):
    r = math.radians(roll_deg) * 0.5
    p = math.radians(pitch_deg) * 0.5
    y = math.radians(yaw_deg) * 0.5
    cr = math.cos(r)
    sr = math.sin(r)
    cp = math.cos(p)
    sp = math.sin(p)
    cy = math.cos(y)
    sy = math.sin(y)
    return quat_normalize((
        cr * cp * cy + sr * sp * sy,
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
    ))


def euler_from_quat(q):
    q0, q1, q2, q3 = q
    roll = math.atan2(2.0 * (q0 * q1 + q2 * q3), 1.0 - 2.0 * (q1 * q1 + q2 * q2))
    s = 2.0 * (q0 * q2 - q3 * q1)
    s = clamp(s, -1.0, 1.0)
    pitch = math.asin(s)
    yaw = math.atan2(2.0 * (q0 * q3 + q1 * q2), 1.0 - 2.0 * (q2 * q2 + q3 * q3))
    return math.degrees(roll), math.degrees(pitch), math.degrees(yaw)


def accel_angles(ax, ay, az):
    roll = math.degrees(math.atan2(ay, az))
    pitch = math.degrees(math.atan2(-ax, math.sqrt(ay * ay + az * az)))
    return roll, pitch


def mag_yaw(mx, my, mz, roll_deg, pitch_deg):
    roll = math.radians(roll_deg)
    pitch = math.radians(pitch_deg)
    mx2 = mx * math.cos(pitch) + mz * math.sin(pitch)
    my2 = (
        mx * math.sin(roll) * math.sin(pitch)
        + my * math.cos(roll)
        - mz * math.sin(roll) * math.cos(pitch)
    )
    return math.degrees(math.atan2(-my2, mx2))


def rotate_body_to_nav(q, bx, by, bz):
    q0, q1, q2, q3 = q
    r00 = 1.0 - 2.0 * (q2 * q2 + q3 * q3)
    r01 = 2.0 * (q1 * q2 - q0 * q3)
    r02 = 2.0 * (q1 * q3 + q0 * q2)
    r10 = 2.0 * (q1 * q2 + q0 * q3)
    r11 = 1.0 - 2.0 * (q1 * q1 + q3 * q3)
    r12 = 2.0 * (q2 * q3 - q0 * q1)
    r20 = 2.0 * (q1 * q3 - q0 * q2)
    r21 = 2.0 * (q2 * q3 + q0 * q1)
    r22 = 1.0 - 2.0 * (q1 * q1 + q2 * q2)
    return (
        r00 * bx + r01 * by + r02 * bz,
        r10 * bx + r11 * by + r12 * bz,
        r20 * bx + r21 * by + r22 * bz,
    )


def init_imu(i2c):
    i2c.writeto_mem(MPU_ADDR, 0x6B, b"\x00")
    time.sleep_ms(100)
    i2c.writeto_mem(MPU_ADDR, 0x1A, b"\x03")
    i2c.writeto_mem(MPU_ADDR, 0x1B, b"\x00")
    i2c.writeto_mem(MPU_ADDR, 0x1C, b"\x00")
    time.sleep_ms(100)


def init_mag(i2c):
    i2c.writeto_mem(MAG_ADDR, 0x00, b"\x70")
    i2c.writeto_mem(MAG_ADDR, 0x01, b"\x20")
    i2c.writeto_mem(MAG_ADDR, 0x02, b"\x00")
    time.sleep_ms(100)


def read_imu(i2c):
    raw = i2c.readfrom_mem(MPU_ADDR, 0x3B, 14)
    ax, ay, az, temp, gx, gy, gz = struct.unpack(">hhhhhhh", raw)
    rx = ax / 16384.0
    ry = ay / 16384.0
    rz = az / 16384.0
    ax_g = ACC_C00 * rx + ACC_C01 * ry + ACC_C02 * rz + ACC_D0
    ay_g = ACC_C10 * rx + ACC_C11 * ry + ACC_C12 * rz + ACC_D1
    az_g = ACC_C20 * rx + ACC_C21 * ry + ACC_C22 * rz + ACC_D2
    return (
        ax_g,
        ay_g,
        az_g,
        temp / 340.0 + 36.53,
        gx / 131.0 - GYRO_BIAS_X,
        gy / 131.0 - GYRO_BIAS_Y,
        gz / 131.0 - GYRO_BIAS_Z,
    )


def read_mag(i2c):
    raw = i2c.readfrom_mem(MAG_ADDR, 0x03, 6)
    x, z, y = struct.unpack(">hhh", raw)
    x -= MAG_BIAS_X
    y -= MAG_BIAS_Y
    z -= MAG_BIAS_Z
    cx = MAG_M00 * x + MAG_M01 * y + MAG_M02 * z
    cy = MAG_M10 * x + MAG_M11 * y + MAG_M12 * z
    cz = MAG_M20 * x + MAG_M21 * y + MAG_M22 * z
    return cx, cy, cz


class MahonyPI:
    def __init__(self, kp, ki):
        self.kp = kp
        self.ki = ki
        self.q = (1.0, 0.0, 0.0, 0.0)
        self.ix = 0.0
        self.iy = 0.0
        self.iz = 0.0
        self.initialized = False

    def init_from_acc_mag(self, ax, ay, az, mx, my, mz):
        ar, ap = accel_angles(ax, ay, az)
        ayaw = mag_yaw(mx, my, mz, ar, ap)
        self.q = quat_from_euler(ar, ap, ayaw)
        self.initialized = True

    def update(self, gx_dps, gy_dps, gz_dps, ax, ay, az, mx, my, mz, dt):
        ax, ay, az = normalize3(ax, ay, az)
        mx, my, mz = normalize3(mx, my, mz)
        if ax == 0 and ay == 0 and az == 0:
            return euler_from_quat(self.q)
        if not self.initialized:
            self.init_from_acc_mag(ax, ay, az, mx, my, mz)

        q0, q1, q2, q3 = self.q
        vx = 2.0 * (q1 * q3 - q0 * q2)
        vy = 2.0 * (q0 * q1 + q2 * q3)
        vz = q0 * q0 - q1 * q1 - q2 * q2 + q3 * q3

        h = quat_mul(self.q, quat_mul((0.0, mx, my, mz), (q0, -q1, -q2, -q3)))
        bx = math.sqrt(h[1] * h[1] + h[2] * h[2])
        bz = h[3]
        wx = 2.0 * bx * (0.5 - q2 * q2 - q3 * q3) + 2.0 * bz * (q1 * q3 - q0 * q2)
        wy = 2.0 * bx * (q1 * q2 - q0 * q3) + 2.0 * bz * (q0 * q1 + q2 * q3)
        wz = 2.0 * bx * (q0 * q2 + q1 * q3) + 2.0 * bz * (0.5 - q1 * q1 - q2 * q2)

        ex = (ay * vz - az * vy) + (my * wz - mz * wy)
        ey = (az * vx - ax * vz) + (mz * wx - mx * wz)
        ez = (ax * vy - ay * vx) + (mx * wy - my * wx)

        self.ix += ex * dt
        self.iy += ey * dt
        self.iz += ez * dt

        gx = math.radians(gx_dps) + self.kp * ex + self.ki * self.ix
        gy = math.radians(gy_dps) + self.kp * ey + self.ki * self.iy
        gz = math.radians(gz_dps) + self.kp * ez + self.ki * self.iz

        q_dot = quat_mul(self.q, (0.0, gx, gy, gz))
        self.q = quat_normalize((
            q0 + 0.5 * q_dot[0] * dt,
            q1 + 0.5 * q_dot[1] * dt,
            q2 + 0.5 * q_dot[2] * dt,
            q3 + 0.5 * q_dot[3] * dt,
        ))
        return euler_from_quat(self.q)


def nmea_checksum_ok(sentence):
    if "*" not in sentence:
        return True
    try:
        body, checksum = sentence[1:].split("*", 1)
        calc = 0
        for ch in body:
            calc ^= ord(ch)
        return calc == int(checksum[:2], 16)
    except Exception:
        return False


def parse_latlon(value, hemi):
    if not value:
        return None
    raw = float(value)
    degrees = int(raw // 100)
    minutes = raw - degrees * 100
    result = degrees + minutes / 60.0
    if hemi == "S" or hemi == "W":
        result = -result
    return result


class GPSParser:
    def __init__(self):
        self.lat = 0.0
        self.lon = 0.0
        self.alt = 0.0
        self.sats = 0
        self.hdop = 99.0
        self.fix_quality = 0
        self.valid = False
        self.utc = ""
        self.speed_mps = 0.0
        self.last_fix_ms = -1000000
        self.nmea_count = 0
        self.fix_count = 0
        self.line_buf = ""
        self.checksum_fail_count = 0

    def feed(self, line, now_ms):
        if not line or not line.startswith("$"):
            return False
        self.nmea_count += 1
        if not nmea_checksum_ok(line):
            self.checksum_fail_count += 1
            return False
        parts = line.split("*", 1)[0].split(",")
        typ = parts[0]
        updated = False
        try:
            if typ.endswith("RMC") and len(parts) >= 10:
                self.utc = parts[1]
                if parts[2] == "A":
                    lat = parse_latlon(parts[3], parts[4])
                    lon = parse_latlon(parts[5], parts[6])
                    if lat is not None and lon is not None:
                        self.lat = lat
                        self.lon = lon
                        self.speed_mps = float(parts[7]) * 0.514444 if parts[7] else 0.0
                        self.valid = True
            elif typ.endswith("GGA") and len(parts) >= 10:
                self.utc = parts[1]
                quality = int(parts[6]) if parts[6] else 0
                self.fix_quality = quality
                self.sats = int(parts[7]) if parts[7] else 0
                self.hdop = float(parts[8]) if parts[8] else 99.0
                if quality > 0:
                    lat = parse_latlon(parts[2], parts[3])
                    lon = parse_latlon(parts[4], parts[5])
                    if lat is not None and lon is not None:
                        self.lat = lat
                        self.lon = lon
                        self.alt = float(parts[9]) if parts[9] else 0.0
                        self.valid = True
                        self.last_fix_ms = now_ms
                        self.fix_count += 1
                        updated = True
        except Exception:
            return False
        return updated

    def usable(self):
        return self.valid and self.fix_quality > 0 and self.sats >= QUALITY_MIN_SATS and self.hdop <= QUALITY_MAX_HDOP


class LocalFrame:
    def __init__(self, lat0, lon0, alt0):
        self.lat0 = lat0
        self.lon0 = lon0
        self.alt0 = alt0
        self.r_earth = 6378137.0
        self.cos_lat0 = math.cos(math.radians(lat0))

    def lla_to_enu(self, lat, lon, alt):
        east = math.radians(lon - self.lon0) * self.r_earth * self.cos_lat0
        north = math.radians(lat - self.lat0) * self.r_earth
        up = alt - self.alt0
        return [east, north, up]

    def enu_to_lla(self, p):
        lat = self.lat0 + math.degrees(p[1] / self.r_earth)
        lon = self.lon0 + math.degrees(p[0] / (self.r_earth * self.cos_lat0))
        alt = self.alt0 + p[2]
        return lat, lon, alt


def make_matrix(n, diag):
    p = []
    for i in range(n):
        row = [0.0] * n
        row[i] = diag[i]
        p.append(row)
    return p


class ESKF15:
    def __init__(self, q0):
        self.p = [0.0, 0.0, 0.0]
        self.v = [0.0, 0.0, 0.0]
        self.q = q0
        self.bg = [0.0, 0.0, 0.0]
        self.ba = [0.0, 0.0, 0.0]
        self.P = make_matrix(15, [
            25.0, 25.0, 100.0,
            4.0, 4.0, 9.0,
            math.radians(8) ** 2, math.radians(8) ** 2, math.radians(20) ** 2,
            math.radians(0.5) ** 2, math.radians(0.5) ** 2, math.radians(0.8) ** 2,
            0.08 ** 2, 0.08 ** 2, 0.12 ** 2,
        ])
        self.innov_xy = 0.0
        self.update_count = 0
        self.reject_count = 0

    def predict(self, dt, q_att, ax_g, ay_g, az_g):
        dt = clamp(dt, 0.002, 0.2)
        self.q = q_att

        axn, ayn, azn = rotate_body_to_nav(self.q, ax_g * G, ay_g * G, az_g * G)
        azn -= G
        axn *= ACCEL_NAV_GAIN
        ayn *= ACCEL_NAV_GAIN
        azn *= ACCEL_NAV_GAIN
        mag = math.sqrt(axn * axn + ayn * ayn + azn * azn)
        if mag > MAX_NAV_ACCEL:
            s = MAX_NAV_ACCEL / mag
            axn *= s
            ayn *= s
            azn *= s

        a = [axn - self.ba[0], ayn - self.ba[1], azn - self.ba[2]]
        for k in range(3):
            self.p[k] += self.v[k] * dt + 0.5 * a[k] * dt * dt
            self.v[k] += a[k] * dt

        damp = 1.0 - VELOCITY_DAMPING * dt
        if damp < 0.90:
            damp = 0.90
        for k in range(3):
            self.v[k] *= damp
        spd = math.sqrt(self.v[0] * self.v[0] + self.v[1] * self.v[1] + self.v[2] * self.v[2])
        if spd > MAX_SPEED_MPS:
            s = MAX_SPEED_MPS / spd
            self.v[0] *= s
            self.v[1] *= s
            self.v[2] *= s

        # Lightweight covariance propagation with the full 15D covariance kept.
        q_pos = 0.0004
        q_acc = 0.45 * 0.45
        q_gyr = math.radians(1.5) ** 2
        q_bg = math.radians(0.08) ** 2
        q_ba = 0.015 * 0.015
        for k in range(3):
            ip = k
            iv = k + 3
            it = k + 6
            ibg = k + 9
            iba = k + 12
            self.P[ip][ip] += 2.0 * self.P[ip][iv] * dt + self.P[iv][iv] * dt * dt + q_pos * dt
            self.P[ip][iv] += self.P[iv][iv] * dt
            self.P[iv][ip] = self.P[ip][iv]
            self.P[iv][iv] += (q_acc + self.P[iba][iba]) * dt
            self.P[it][it] += (q_gyr + self.P[ibg][ibg]) * dt
            self.P[ibg][ibg] += q_bg * dt
            self.P[iba][iba] += q_ba * dt
            # Keep covariance numerically bounded for long demos.
            self.P[ip][ip] = clamp(self.P[ip][ip], 0.25, 2500.0)
            self.P[iv][iv] = clamp(self.P[iv][iv], 0.01, 400.0)
            self.P[it][it] = clamp(self.P[it][it], math.radians(1) ** 2, math.radians(90) ** 2)

    def inject(self, dx):
        for k in range(3):
            self.p[k] += dx[k]
            self.v[k] += dx[k + 3]
            self.bg[k] += dx[k + 9]
            self.ba[k] += dx[k + 12]
        dq = small_angle_quat(dx[6], dx[7], dx[8])
        self.q = quat_normalize(quat_mul(dq, self.q))

    def scalar_update(self, obs_index, innovation, r_var):
        s = self.P[obs_index][obs_index] + r_var
        if s <= 0:
            return
        kvec = [self.P[i][obs_index] / s for i in range(15)]
        dx = [0.0] * 15
        for i in range(15):
            dx[i] = kvec[i] * innovation
        row = self.P[obs_index][:]
        for i in range(15):
            ki = kvec[i]
            for j in range(15):
                self.P[i][j] -= ki * row[j]
        self.inject(dx)

    def apply_stationary_constraints(self, anchor):
        r_v = ZUPT_SIGMA_MPS * ZUPT_SIGMA_MPS
        for k in range(3):
            self.scalar_update(k + 3, -self.v[k], r_v)

        r_p = POS_HOLD_SIGMA_M * POS_HOLD_SIGMA_M
        for k in range(3):
            self.scalar_update(k, anchor[k] - self.p[k], r_p)

        for i in range(15):
            if self.P[i][i] < 1e-9:
                self.P[i][i] = 1e-9

    def update_gps(self, z, hdop, stationary=False):
        innovation = [z[0] - self.p[0], z[1] - self.p[1], z[2] - self.p[2]]
        self.innov_xy = math.sqrt(innovation[0] * innovation[0] + innovation[1] * innovation[1])
        sigma_xy = clamp(2.8 * hdop, 2.5, 25.0)
        sigma_z = clamp(4.5 * hdop, 8.0, 45.0)
        if stationary:
            sigma_xy *= STATIC_GPS_SIGMA_SCALE
            sigma_z *= STATIC_GPS_SIGMA_SCALE
        gate = max(45.0, 12.0 * sigma_xy)
        if self.innov_xy > gate:
            self.reject_count += 1
            return False

        dx = [0.0] * 15
        r_diag = [sigma_xy * sigma_xy, sigma_xy * sigma_xy, sigma_z * sigma_z]
        for obs in range(3):
            s = self.P[obs][obs] + r_diag[obs]
            if s <= 0:
                continue
            kvec = [self.P[i][obs] / s for i in range(15)]
            y = innovation[obs]
            for i in range(15):
                dx[i] += kvec[i] * y
            row = self.P[obs][:]
            for i in range(15):
                ki = kvec[i]
                for j in range(15):
                    self.P[i][j] -= ki * row[j]

        self.inject(dx)
        for i in range(15):
            if self.P[i][i] < 1e-9:
                self.P[i][i] = 1e-9
        self.update_count += 1
        return True


def read_gps_lines(uart, parser, now_ms):
    got_update = False
    loops = 0
    while uart.any() and loops < 8:
        loops += 1
        n = uart.any()
        if n > 128:
            n = 128
        raw = uart.read(n)
        if not raw:
            continue
        try:
            parser.line_buf += raw.decode("ascii")
        except Exception:
            continue
        if len(parser.line_buf) > 512:
            parser.line_buf = parser.line_buf[-512:]

    line_count = 0
    while "\n" in parser.line_buf and line_count < 12:
        line_count += 1
        line, parser.line_buf = parser.line_buf.split("\n", 1)
        line = line.strip()
        if parser.feed(line, now_ms):
            got_update = True
    return got_update


def print_header():
    print("ESP32 real-time 15D simplified ESKF")
    print("state: dx=[dp,dv,dtheta,dbg,dba], nominal=[p,v,q,bg,ba]")
    print("ESKF15_HEADER,t_ms,initialized,gps_fix,sats,hdop,gps_lat,gps_lon,gps_alt,est_lat,est_lon,est_alt,e_m,n_m,u_m,ve_mps,vn_mps,vu_mps,roll_deg,pitch_deg,yaw_deg,innov_xy_m,sigma_e_m,sigma_n_m,imu_hz,gps_updates,gps_rejects,nmea_count")


def main():
    status_led = Pin(STATUS_LED_PIN, Pin.OUT)
    led_write(status_led, True)
    time.sleep_ms(800)
    led_write(status_led, False)

    i2c = I2C(0, sda=Pin(SDA_PIN), scl=Pin(SCL_PIN), freq=I2C_FREQ)
    scan = i2c.scan()
    print("scan:", [hex(x) for x in scan])
    if MPU_ADDR not in scan:
        print("ERROR: IMU 0x68 not found")
        return
    if MAG_ADDR not in scan:
        print("ERROR: HMC5883L 0x1E not found")
        return
    init_imu(i2c)
    init_mag(i2c)

    uart = UART(
        GPS_UART_ID,
        baudrate=GPS_BAUDRATE,
        bits=8,
        parity=None,
        stop=1,
        rx=Pin(GPS_RX_PIN),
        tx=Pin(GPS_TX_PIN),
        timeout=0,
    )
    gps = GPSParser()
    mahony = MahonyPI(MAHONY_KP, MAHONY_KI)
    frame = None
    eskf = None
    initialized = False

    print_header()
    t0 = ticks_ms()
    last_t = t0
    next_t = t0
    last_print = t0
    fps_t0 = t0
    fps_count = 0
    imu_hz = 0.0
    stationary_count = 0
    stationary_anchor = None
    last_stationary_update = t0

    while True:
        now = ticks_ms()
        dt = max(0.001, ticks_diff(now, last_t) / 1000.0)
        last_t = now

        gps_updated = read_gps_lines(uart, gps, now)

        try:
            ax, ay, az, temp, gx, gy, gz = read_imu(i2c)
            mx, my, mz = read_mag(i2c)
        except Exception as exc:
            print("ERROR:sensor_read,%r" % (exc,))
            time.sleep_ms(200)
            continue

        roll, pitch, yaw = mahony.update(gx, gy, gz, ax, ay, az, mx, my, mz, dt)
        acc_norm = math.sqrt(ax * ax + ay * ay + az * az)
        gyro_norm = math.sqrt(gx * gx + gy * gy + gz * gz)
        if abs(acc_norm - 1.0) < STATIONARY_ACC_NORM_THR_G and gyro_norm < STATIONARY_GYRO_NORM_THR_DPS:
            stationary_count += 1
        else:
            stationary_count = 0
            stationary_anchor = None
        stationary = stationary_count >= STATIONARY_COUNT_MIN

        fps_count += 1
        elapsed = ticks_diff(now, fps_t0)
        if elapsed >= 1000:
            imu_hz = fps_count * 1000.0 / elapsed
            fps_count = 0
            fps_t0 = now

        if (not initialized) and gps.usable() and mahony.initialized:
            frame = LocalFrame(gps.lat, gps.lon, gps.alt)
            eskf = ESKF15(mahony.q)
            initialized = True
            print("# origin,%.8f,%.8f,%.3f" % (gps.lat, gps.lon, gps.alt))

        if initialized:
            eskf.predict(dt, mahony.q, ax, ay, az)
            if stationary:
                if stationary_anchor is None:
                    stationary_anchor = eskf.p[:]
                if ticks_diff(now, last_stationary_update) >= STATIONARY_UPDATE_MS:
                    eskf.apply_stationary_constraints(stationary_anchor)
                    last_stationary_update = now
            if gps_updated and gps.usable():
                z = frame.lla_to_enu(gps.lat, gps.lon, gps.alt)
                eskf.update_gps(z, gps.hdop, stationary)

        if initialized:
            mode = 2 if ticks_diff(now, gps.last_fix_ms) < 3000 else 1
        else:
            mode = 1 if gps.valid else 0
        update_led(status_led, mode, now, t0)

        if ticks_diff(now, last_print) >= int(1000 / PRINT_HZ):
            last_print = now
            if initialized:
                lat, lon, alt = frame.enu_to_lla(eskf.p)
                sigma_e = math.sqrt(max(eskf.P[0][0], 0.0))
                sigma_n = math.sqrt(max(eskf.P[1][1], 0.0))
                print(
                    "ESKF15,%d,1,%d,%d,%.2f,%.8f,%.8f,%.2f,%.8f,%.8f,%.2f,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f,%.2f,%.2f,%.2f,%.3f,%.3f,%.3f,%.2f,%d,%d,%d"
                    % (
                        now, gps.fix_quality, gps.sats, gps.hdop,
                        gps.lat, gps.lon, gps.alt,
                        lat, lon, alt,
                        eskf.p[0], eskf.p[1], eskf.p[2],
                        eskf.v[0], eskf.v[1], eskf.v[2],
                        roll, pitch, yaw,
                        eskf.innov_xy, sigma_e, sigma_n,
                        imu_hz, eskf.update_count, eskf.reject_count, gps.nmea_count,
                    )
                )
            else:
                print(
                    "ESKF15,%d,0,%d,%d,%.2f,%.8f,%.8f,%.2f,0,0,0,0,0,0,0,0,0,%.2f,%.2f,%.2f,0,0,0,%.2f,0,0,%d"
                    % (
                        now, gps.fix_quality, gps.sats, gps.hdop,
                        gps.lat, gps.lon, gps.alt,
                        roll, pitch, yaw, imu_hz, gps.nmea_count,
                    )
                )

        next_t = time.ticks_add(next_t, int(1000 / TARGET_HZ))
        wait_ms = time.ticks_diff(next_t, time.ticks_ms())
        if wait_ms > 0:
            time.sleep_ms(wait_ms)


try:
    main()
except Exception as exc:
    print("ESKF15_FATAL,%r" % (exc,))
    try:
        led = Pin(STATUS_LED_PIN, Pin.OUT)
        state = False
        while True:
            state = not state
            led_write(led, state)
            time.sleep_ms(120)
    except Exception:
        raise
