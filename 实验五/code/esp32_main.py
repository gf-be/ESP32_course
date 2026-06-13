from machine import I2C, Pin
from time import sleep_ms, ticks_us
from math import atan2, cos, pi, sin, sqrt


# Modes:
# 0 = verify HMC5883L ID and initialization
# 1 = output raw magnetic data: MAG,t,bx,by,bz
# 2 = output heading data: HEAD,t,yaw_raw,yaw_cal,|B_cal|
# 3 = output MPU6050 tilt compensation data:
#     TILT,t,roll,pitch,ax,ay,az,yaw_raw,yaw_cal,yaw_tilt,|B_cal|
# 4 = MPU6050-only tilt debug: IMU,t,roll,pitch,ax,ay,az
# 9 = low-level register diagnostics
APP_MODE = 3

# "single" is slower but more reliable on many GY-273/HMC5883L modules.
# Change to "continuous" only after single-shot readings are confirmed normal.
READ_MODE = "single"

I2C_SDA = 21
I2C_SCL = 22
I2C_FREQ = 50000

START_DELAY_MS = 5000
RUN_COUNTER_FILE = "lab05_run_id.txt"
SAVE_TO_FILE = True
SAMPLE_LIMIT = 1500
FLUSH_EVERY = 25
MAG_FILE_PREFIX = "mag_run_"
LOG_FILE_PREFIX = "log_run_"

# Most ESP32 DevKit boards expose the programmable onboard LED on GPIO2.
# Power/charging LEDs are hardware-only and cannot be blinked by MicroPython.
LED_PINS = [2]
LED_ACTIVE_HIGH = True

HMC5883L_ADDR = 0x1E
REG_CRA = 0x00
REG_CRB = 0x01
REG_MODE = 0x02
REG_DATA = 0x03
REG_STATUS = 0x09
REG_ID = 0x0A

GAIN_LSB_PER_GAUSS = 1090.0
GAUSS_TO_UT = 100.0
HMC_CRA_VALUE = 0x70

MPU6050_ADDR = 0x68
MPU_REG_PWR_MGMT_1 = 0x6B
MPU_REG_WHO_AM_I = 0x75
MPU_REG_ACCEL_XOUT_H = 0x3B
ACCEL_LSB_PER_G = 16384.0

# Replace these values after running scripts/ellipsoid_fit.py.
MAG_C = [6.941098, -5.327788, 1.117477]
MAG_W = [
    [1.02631523, 0.01149070, -0.00769252],
    [0.01149070, 0.97130921, 0.04320549],
    [-0.00769252, 0.04320549, 0.97699664],
]


def make_leds():
    leds = []
    for pin_no in LED_PINS:
        try:
            led = Pin(pin_no, Pin.OUT)
            led.value(0 if LED_ACTIVE_HIGH else 1)
            leds.append(led)
        except Exception:
            pass
    return leds


LEDS = make_leds()


def set_leds(on):
    value = 1 if (on == LED_ACTIVE_HIGH) else 0
    for led in LEDS:
        led.value(value)


def blink_leds(times=1, on_ms=80, off_ms=80):
    for _ in range(times):
        set_leds(True)
        sleep_ms(on_ms)
        set_leds(False)
        sleep_ms(off_ms)


def startup_light_show():
    blink_leds(times=6, on_ms=90, off_ms=90)
    sleep_ms(200)
    blink_leds(times=2, on_ms=220, off_ms=160)


def sample_ok_blink():
    blink_leds(times=1, on_ms=25, off_ms=10)


def error_blink():
    blink_leds(times=3, on_ms=60, off_ms=60)


def done_blink_forever():
    while True:
        blink_leds(times=1, on_ms=700, off_ms=700)


def next_run_id():
    run_id = None
    try:
        with open(RUN_COUNTER_FILE, "r") as f:
            text = f.read().strip()
            if text:
                run_id = int(text)
    except Exception:
        run_id = None

    if run_id is None:
        run_id = ticks_us() & 0x7FFFFFFF
    else:
        run_id += 1

    try:
        with open(RUN_COUNTER_FILE, "w") as f:
            f.write(str(run_id))
    except Exception:
        pass

    return run_id


def unique_filename(prefix, run_id, ext):
    index = 0
    while True:
        if index == 0:
            filename = "{}{}.{}".format(prefix, run_id, ext)
        else:
            filename = "{}{}_{}.{}".format(prefix, run_id, index, ext)

        try:
            with open(filename, "r"):
                pass
            index += 1
        except OSError:
            return filename


def unique_mag_filename(run_id):
    return unique_filename(MAG_FILE_PREFIX, run_id, "csv")


def unique_log_filename(run_id):
    return unique_filename(LOG_FILE_PREFIX, run_id, "txt")


def log_event(log_file, message):
    print(message)
    if log_file:
        try:
            log_file.write(message + "\n")
            log_file.flush()
        except Exception:
            pass


def wait_before_collection(run_id):
    seconds = START_DELAY_MS // 1000
    print("RUN,{},START_DELAY,{}s".format(run_id, seconds))
    for remaining in range(seconds, 0, -1):
        print("RUN,{},COUNTDOWN,{}".format(run_id, remaining))
        blink_leds(times=1, on_ms=120, off_ms=80)
        sleep_ms(800)


class HMC5883L:
    def __init__(self, i2c, addr=HMC5883L_ADDR):
        self.i2c = i2c
        self.addr = addr

    def write_reg(self, reg, value):
        last_error = None
        for _ in range(3):
            try:
                self.i2c.writeto_mem(self.addr, reg, bytes([value & 0xFF]))
                return
            except OSError as exc:
                last_error = exc
                sleep_ms(5)
        raise last_error

    def read_reg(self, reg, n):
        last_error = None
        for _ in range(3):
            try:
                return self.i2c.readfrom_mem(self.addr, reg, n)
            except OSError as exc:
                last_error = exc
                sleep_ms(5)
        raise last_error

    def read_id(self):
        raw = self.read_reg(REG_ID, 3)
        return raw.decode("ascii", "ignore")

    def init(self):
        chip_id = self.read_id()
        if chip_id != "H43":
            raise OSError("HMC5883L ID wrong: {}".format(repr(chip_id)))

        self.write_reg(REG_MODE, 0x03)  # idle before reconfiguration
        sleep_ms(5)
        self.write_reg(REG_CRA, HMC_CRA_VALUE)  # conservative setup from lab manual
        self.write_reg(REG_CRB, 0x20)   # +/-1.3 Gauss, 1090 LSB/Gauss
        if READ_MODE == "continuous":
            self.write_reg(REG_MODE, 0x00)
        else:
            self.write_reg(REG_MODE, 0x01)
        sleep_ms(20)
        return chip_id

    def print_config(self):
        cra = self.read_reg(REG_CRA, 1)[0]
        crb = self.read_reg(REG_CRB, 1)[0]
        mode = self.read_reg(REG_MODE, 1)[0]
        print("HMC5883L config: CRA=0x{:02X}, CRB=0x{:02X}, MODE=0x{:02X}".format(cra, crb, mode))

    def dump_registers(self, start=0x00, end=0x0C):
        values = []
        for reg in range(start, end + 1):
            try:
                values.append(self.read_reg(reg, 1)[0])
            except Exception:
                values.append(None)

        print("Register dump:")
        for reg, value in zip(range(start, end + 1), values):
            if value is None:
                print("  0x{:02X}: ERR".format(reg))
            else:
                print("  0x{:02X}: 0x{:02X}".format(reg, value))

    def diagnostic(self):
        print("=== HMC5883L diagnostic ===")
        self.dump_registers()

        tests = [
            (REG_CRA, 0x10, "CRA default-like"),
            (REG_CRA, 0x70, "CRA lab manual setup"),
            (REG_CRA, 0x78, "CRA 8-average 75Hz"),
            (REG_CRB, 0x20, "CRB +/-1.3G"),
            (REG_CRB, 0x00, "CRB +/-0.88G"),
            (REG_CRB, 0x20, "CRB restore +/-1.3G"),
            (REG_MODE, 0x00, "MODE continuous"),
            (REG_MODE, 0x01, "MODE single"),
        ]

        for reg, value, label in tests:
            print("Write {}: reg 0x{:02X} <- 0x{:02X}".format(label, reg, value))
            self.write_reg(reg, value)
            sleep_ms(20)
            got = self.read_reg(reg, 1)[0]
            print("  readback reg 0x{:02X} = 0x{:02X}".format(reg, got))

        print("Trigger single measurements and read raw data bytes:")
        for i in range(5):
            self.write_reg(REG_MODE, 0x01)
            sleep_ms(30)
            status = self.read_reg(REG_STATUS, 1)[0]
            data = self.read_reg(REG_DATA, 6)
            print(
                "  sample {}: SR=0x{:02X}, bytes={}, raw={}".format(
                    i + 1,
                    status,
                    ["0x{:02X}".format(x) for x in data],
                    self.read_raw(),
                )
            )

    def data_ready(self):
        status = self.read_reg(REG_STATUS, 1)[0]
        return (status & 0x01) != 0

    def _i16(self, msb, lsb):
        value = (msb << 8) | lsb
        if value & 0x8000:
            value -= 65536
        return value

    def read_raw(self):
        if READ_MODE == "single":
            try:
                self.read_reg(REG_DATA, 6)  # clear possible LOCK state
            except Exception:
                pass
            self.write_reg(REG_MODE, 0x03)
            sleep_ms(5)
            self.write_reg(REG_MODE, 0x01)
            sleep_ms(100)
        else:
            # In continuous mode the output registers refresh periodically.
            # Some HMC5883L modules do not expose the RDY bit reliably over
            # MicroPython I2C, so read the 6 data bytes directly after a delay.
            sleep_ms(20)

        data = self.read_reg(REG_DATA, 6)

        # HMC5883L output order is X, Z, Y.
        rx = self._i16(data[0], data[1])
        rz = self._i16(data[2], data[3])
        ry = self._i16(data[4], data[5])

        if rx == -4096 or ry == -4096 or rz == -4096:
            raise OSError("HMC5883L overflow; move away from strong magnetic field")

        return rx, ry, rz

    def read_ut(self):
        rx, ry, rz = self.read_raw()
        bx = rx / GAIN_LSB_PER_GAUSS * GAUSS_TO_UT
        by = ry / GAIN_LSB_PER_GAUSS * GAUSS_TO_UT
        bz = rz / GAIN_LSB_PER_GAUSS * GAUSS_TO_UT
        mag = sqrt(bx * bx + by * by + bz * bz)
        return ticks_us() / 1000000.0, bx, by, bz, mag


class MPU6050:
    def __init__(self, i2c, addr=MPU6050_ADDR):
        self.i2c = i2c
        self.addr = addr
        self.ax0 = 0.0
        self.ay0 = 0.0
        self.az0 = 0.0

    def write_reg(self, reg, value):
        last_error = None
        for _ in range(3):
            try:
                self.i2c.writeto_mem(self.addr, reg, bytes([value & 0xFF]))
                return
            except OSError as exc:
                last_error = exc
                sleep_ms(10)
        raise last_error

    def read_reg(self, reg, n):
        last_error = None
        for _ in range(5):
            try:
                return self.i2c.readfrom_mem(self.addr, reg, n)
            except OSError as exc:
                last_error = exc
                sleep_ms(10)
        raise last_error

    def init(self):
        # Some MPU6500/MPU6050-compatible boards NACK config writes but still
        # stream accel data after power-up. Avoid mandatory writes here.
        sleep_ms(100)

    def who_am_i(self):
        return self.read_reg(MPU_REG_WHO_AM_I, 1)[0]

    def _i16(self, msb, lsb):
        value = (msb << 8) | lsb
        if value & 0x8000:
            value -= 65536
        return value

    def read_accel_g(self):
        data = self.read_reg(MPU_REG_ACCEL_XOUT_H, 6)
        ax = self._i16(data[0], data[1]) / ACCEL_LSB_PER_G
        ay = self._i16(data[2], data[3]) / ACCEL_LSB_PER_G
        az = self._i16(data[4], data[5]) / ACCEL_LSB_PER_G
        return ax, ay, az

    def read_roll_pitch_deg(self):
        ax, ay, az = self.read_accel_g()
        roll = atan2(ay, az) * 180.0 / pi
        pitch = atan2(-ax, sqrt(ay * ay + az * az)) * 180.0 / pi
        return roll, pitch


def calibrate_mag(bx, by, bz):
    m0 = bx - MAG_C[0]
    m1 = by - MAG_C[1]
    m2 = bz - MAG_C[2]

    bx_cal = MAG_W[0][0] * m0 + MAG_W[0][1] * m1 + MAG_W[0][2] * m2
    by_cal = MAG_W[1][0] * m0 + MAG_W[1][1] * m1 + MAG_W[1][2] * m2
    bz_cal = MAG_W[2][0] * m0 + MAG_W[2][1] * m1 + MAG_W[2][2] * m2
    return bx_cal, by_cal, bz_cal


def yaw_deg(bx, by):
    yaw = atan2(-by, bx) * 180.0 / pi
    if yaw < 0:
        yaw += 360.0
    return yaw


def tilt_compensated_yaw_deg(bx, by, bz, roll_deg, pitch_deg):
    roll = roll_deg * pi / 180.0
    pitch = pitch_deg * pi / 180.0

    bx_h = bx * cos(pitch) + by * sin(roll) * sin(pitch) + bz * cos(roll) * sin(pitch)
    by_h = by * cos(roll) - bz * sin(roll)
    return yaw_deg(bx_h, by_h)


def scan_i2c(i2c):
    devices = i2c.scan()
    print("I2C devices:", [hex(x) for x in devices])
    return devices


def main():
    startup_light_show()
    run_id = next_run_id()
    log_file = None
    try:
        log_filename = unique_log_filename(run_id)
        log_file = open(log_filename, "w")
        log_event(log_file, "RUN,{},LOG,{}".format(run_id, log_filename))
    except Exception:
        pass

    log_event(log_file, "RUN,{},BEGIN,APP_MODE={}".format(run_id, APP_MODE))

    try:
        i2c = I2C(0, scl=Pin(I2C_SCL), sda=Pin(I2C_SDA), freq=I2C_FREQ)
        devices = scan_i2c(i2c)
        log_event(log_file, "RUN,{},I2C,{}".format(run_id, [hex(x) for x in devices]))

        if APP_MODE == 4:
            if MPU6050_ADDR not in devices:
                raise OSError("MPU6050 not found at 0x68; check VCC/GND/SCL/SDA")
            mpu = MPU6050(i2c)
            mpu.init()
            log_event(log_file, "MPU6050/compatible detected at 0x68")
            log_event(log_file, "CSV format: IMU,run_id,t_s,roll_deg,pitch_deg,ax_g,ay_g,az_g")
            while True:
                try:
                    ax, ay, az = mpu.read_accel_g()
                    if ax == 0.0 and ay == 0.0 and az == 0.0:
                        raise OSError("MPU accel all zero")
                    roll = atan2(ay, az) * 180.0 / pi
                    pitch = atan2(-ax, sqrt(ay * ay + az * az)) * 180.0 / pi
                    print("IMU,{},{:.3f},{:.2f},{:.2f},{:.3f},{:.3f},{:.3f}".format(
                        run_id, ticks_us() / 1000000.0, roll, pitch, ax, ay, az
                    ))
                    sample_ok_blink()
                except Exception as exc:
                    log_event(log_file, "ERR,{},{}".format(run_id, exc))
                    error_blink()
                sleep_ms(150)

        hmc = HMC5883L(i2c)
        chip_id = hmc.init()
        log_event(log_file, "HMC5883L ID verified: {}".format(chip_id))
        log_event(log_file, "HMC5883L initialized: 75 Hz, +/-1.3 Gauss")
        hmc.print_config()
        blink_leds(times=3, on_ms=120, off_ms=120)

        if APP_MODE == 9:
            hmc.diagnostic()
            if log_file:
                log_file.close()
            return

        if APP_MODE == 0:
            log_event(log_file, "Step 1 complete. Set APP_MODE = 1 for data collection.")
            if log_file:
                log_file.close()
            return

        if APP_MODE == 1:
            wait_before_collection(run_id)
            log_event(log_file, "CSV format: MAG,run_id,t_s,bx_ut,by_ut,bz_ut")

            output_file = None
            filename = ""
            if SAVE_TO_FILE:
                filename = unique_mag_filename(run_id)
                output_file = open(filename, "w")
                output_file.write("run_id,t_s,bx_ut,by_ut,bz_ut\n")
                output_file.flush()
                log_event(log_file, "RUN,{},FILE,{}".format(run_id, filename))

            sample_count = 0
            error_count = 0
            try:
                while sample_count < SAMPLE_LIMIT:
                    try:
                        t, bx, by, bz, mag = hmc.read_ut()
                        line = "{},{:.3f},{:.4f},{:.4f},{:.4f}\n".format(run_id, t, bx, by, bz)
                        print("MAG," + line.strip())
                        if output_file:
                            output_file.write(line)
                            if sample_count % FLUSH_EVERY == 0:
                                output_file.flush()
                        sample_count += 1
                        sample_ok_blink()
                    except Exception as exc:
                        error_count += 1
                        log_event(log_file, "ERR,{},{}".format(run_id, exc))
                        error_blink()
                    sleep_ms(20)
            finally:
                if output_file:
                    output_file.flush()
                    output_file.close()

            log_event(log_file, "RUN,{},DONE,samples={},errors={},file={}".format(run_id, sample_count, error_count, filename))
            if log_file:
                log_file.close()
            done_blink_forever()

        if APP_MODE == 2:
            wait_before_collection(run_id)
            log_event(log_file, "CSV format: HEAD,run_id,t_s,yaw_raw_deg,yaw_cal_deg,b_cal_ut")
            while True:
                try:
                    t, bx, by, bz, mag = hmc.read_ut()
                    bx_cal, by_cal, bz_cal = calibrate_mag(bx, by, bz)
                    raw_yaw = yaw_deg(bx, by)
                    cal_yaw = yaw_deg(bx_cal, by_cal)
                    b_cal = sqrt(bx_cal * bx_cal + by_cal * by_cal + bz_cal * bz_cal)
                    print("HEAD,{},{:.3f},{:.2f},{:.2f},{:.2f}".format(run_id, t, raw_yaw, cal_yaw, b_cal))
                    sample_ok_blink()
                except Exception as exc:
                    log_event(log_file, "ERR,{},{}".format(run_id, exc))
                    error_blink()
                sleep_ms(100)

        if APP_MODE == 3:
            if MPU6050_ADDR not in devices:
                raise OSError("MPU6050 not found at 0x68; check VCC/GND/SCL/SDA")

            mpu = MPU6050(i2c)
            mpu.init()
            log_event(log_file, "MPU6050/compatible detected at 0x68")
            wait_before_collection(run_id)
            log_event(log_file, "CSV format: TILT,run_id,t_s,roll_deg,pitch_deg,ax_g,ay_g,az_g,yaw_raw_deg,yaw_cal_deg,yaw_tilt_deg,b_cal_ut")

            while True:
                try:
                    ax, ay, az = mpu.read_accel_g()
                    if ax == 0.0 and ay == 0.0 and az == 0.0:
                        raise OSError("MPU accel all zero")
                    roll = atan2(ay, az) * 180.0 / pi
                    pitch = atan2(-ax, sqrt(ay * ay + az * az)) * 180.0 / pi
                    sleep_ms(20)
                    t, bx, by, bz, mag = hmc.read_ut()
                    bx_cal, by_cal, bz_cal = calibrate_mag(bx, by, bz)
                    raw_yaw = yaw_deg(bx, by)
                    cal_yaw = yaw_deg(bx_cal, by_cal)
                    tilt_yaw = tilt_compensated_yaw_deg(bx_cal, by_cal, bz_cal, roll, pitch)
                    b_cal = sqrt(bx_cal * bx_cal + by_cal * by_cal + bz_cal * bz_cal)
                    print(
                        "TILT,{},{:.3f},{:.2f},{:.2f},{:.3f},{:.3f},{:.3f},{:.2f},{:.2f},{:.2f},{:.2f}".format(
                            run_id, t, roll, pitch, ax, ay, az, raw_yaw, cal_yaw, tilt_yaw, b_cal
                        )
                    )
                    sample_ok_blink()
                except Exception as exc:
                    log_event(log_file, "ERR,{},{}".format(run_id, exc))
                    error_blink()
                sleep_ms(150)
    except Exception as exc:
        log_event(log_file, "RUN,{},FATAL,{}".format(run_id, exc))
        if log_file:
            try:
                log_file.close()
            except Exception:
                pass
        error_blink()
        done_blink_forever()


main()
