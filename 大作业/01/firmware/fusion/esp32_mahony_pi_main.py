"""
ESP32 MicroPython Mahony PI real-time attitude program.

Upload this file to ESP32 as main.py, or open it in Thonny and run it on the
MicroPython device. It reads IMU + HMC5883L magnetometer data and prints
real-time roll/pitch/yaw through the serial port.

Hardware used in the current project:
  I2C SDA = GPIO21
  I2C SCL = GPIO22
  IMU address = 0x68
  HMC5883L address = 0x1E
"""

from machine import Pin, I2C
import time
import struct
import math


SDA_PIN = 21
SCL_PIN = 22
I2C_FREQ = 400000
MPU_ADDR = 0x68
MAG_ADDR = 0x1E

TARGET_HZ = 100

# From gyro Allan variance experiment.
GYRO_BIAS_X = 0.228303741
GYRO_BIAS_Y = 0.964654373
GYRO_BIAS_Z = -0.100939275

# From magnetometer ellipsoid calibration.
MAG_BIAS_X = 77.082135
MAG_BIAS_Y = -94.427834
MAG_BIAS_Z = -36.852085

# Simplified soft-iron compensation matrix from ellipsoid calibration.
MAG_M00 = 1.006948
MAG_M01 = -0.000000
MAG_M02 = 0.000000
MAG_M10 = -0.000000
MAG_M11 = 1.020430
MAG_M12 = 0.000000
MAG_M20 = 0.000000
MAG_M21 = 0.000000
MAG_M22 = 1.043697

# Mahony PI gains. Keep moderate for hand-held demo stability.
KP = 1.2
KI = 0.02


def inv_sqrt(x):
    if x <= 0:
        return 0.0
    return 1.0 / math.sqrt(x)


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
    if s > 1.0:
        s = 1.0
    elif s < -1.0:
        s = -1.0
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
    return (
        ax / 16384.0,
        ay / 16384.0,
        az / 16384.0,
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

        # Estimated gravity direction from quaternion.
        vx = 2.0 * (q1 * q3 - q0 * q2)
        vy = 2.0 * (q0 * q1 + q2 * q3)
        vz = q0 * q0 - q1 * q1 - q2 * q2 + q3 * q3

        # Estimated magnetic field direction.
        h = quat_mul(self.q, quat_mul((0.0, mx, my, mz), (q0, -q1, -q2, -q3)))
        bx = math.sqrt(h[1] * h[1] + h[2] * h[2])
        bz = h[3]
        wx = 2.0 * bx * (0.5 - q2 * q2 - q3 * q3) + 2.0 * bz * (q1 * q3 - q0 * q2)
        wy = 2.0 * bx * (q1 * q2 - q0 * q3) + 2.0 * bz * (q0 * q1 + q2 * q3)
        wz = 2.0 * bx * (q0 * q2 + q1 * q3) + 2.0 * bz * (0.5 - q1 * q1 - q2 * q2)

        # Error is measured direction cross estimated direction.
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


def main():
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
    filt = MahonyPI(KP, KI)

    interval_ms = int(1000 / TARGET_HZ)
    next_t = time.ticks_ms()
    last_t = next_t
    fps_t0 = next_t
    fps_count = 0
    update_hz = 0.0

    print("Mahony PI real-time attitude")
    print("t_ms,roll_deg,pitch_deg,yaw_deg,temp_c,update_hz")

    while True:
        now = time.ticks_ms()
        dt = max(0.001, time.ticks_diff(now, last_t) / 1000.0)
        last_t = now

        ax, ay, az, temp, gx, gy, gz = read_imu(i2c)
        mx, my, mz = read_mag(i2c)
        roll, pitch, yaw = filt.update(gx, gy, gz, ax, ay, az, mx, my, mz, dt)

        fps_count += 1
        elapsed = time.ticks_diff(now, fps_t0)
        if elapsed >= 1000:
            update_hz = fps_count * 1000.0 / elapsed
            fps_count = 0
            fps_t0 = now

        print("%d,%.3f,%.3f,%.3f,%.3f,%.2f" % (now, roll, pitch, yaw, temp, update_hz))

        next_t = time.ticks_add(next_t, interval_ms)
        wait_ms = time.ticks_diff(next_t, time.ticks_ms())
        if wait_ms > 0:
            time.sleep_ms(wait_ms)


main()
