from machine import Pin, I2C
import time
import struct


SDA_PIN = 21
SCL_PIN = 22
I2C_FREQ = 400000
MPU_ADDR = 0x68

SAMPLE_HZ = 50
DURATION_S = 120
OUTPUT_FILE = "imu_static_120s.csv"


def init_mpu6050(i2c):
    i2c.writeto_mem(MPU_ADDR, 0x6B, b"\x00")  # Wake up.
    time.sleep_ms(100)
    i2c.writeto_mem(MPU_ADDR, 0x1A, b"\x03")  # DLPF about 44 Hz accel, 42 Hz gyro.
    i2c.writeto_mem(MPU_ADDR, 0x1B, b"\x00")  # Gyro +/-250 dps.
    i2c.writeto_mem(MPU_ADDR, 0x1C, b"\x00")  # Accel +/-2 g.
    time.sleep_ms(100)


def read_mpu6050(i2c):
    raw = i2c.readfrom_mem(MPU_ADDR, 0x3B, 14)
    ax, ay, az, temp, gx, gy, gz = struct.unpack(">hhhhhhh", raw)
    return (
        ax / 16384.0,
        ay / 16384.0,
        az / 16384.0,
        temp / 340.0 + 36.53,
        gx / 131.0,
        gy / 131.0,
        gz / 131.0,
    )


def main():
    i2c = I2C(0, sda=Pin(SDA_PIN), scl=Pin(SCL_PIN), freq=I2C_FREQ)
    init_mpu6050(i2c)

    interval_ms = int(1000 / SAMPLE_HZ)
    total = SAMPLE_HZ * DURATION_S

    print("imu_static_logger")
    print("keep the board completely still")
    print("sample_hz,%d" % SAMPLE_HZ)
    print("duration_s,%d" % DURATION_S)
    print("output_file,%s" % OUTPUT_FILE)

    header = "t_ms,ax_g,ay_g,az_g,temp_c,gx_dps,gy_dps,gz_dps\n"
    print(header.strip())

    t0 = time.ticks_ms()
    next_t = t0
    with open(OUTPUT_FILE, "w") as f:
        f.write("# imu_static_logger\n")
        f.write("# sample_hz,%d\n" % SAMPLE_HZ)
        f.write("# duration_s,%d\n" % DURATION_S)
        f.write("# sda_gpio,%d\n" % SDA_PIN)
        f.write("# scl_gpio,%d\n" % SCL_PIN)
        f.write(header)

        for n in range(total):
            now = time.ticks_ms()
            ax, ay, az, temp, gx, gy, gz = read_mpu6050(i2c)
            line = "%d,%.6f,%.6f,%.6f,%.3f,%.6f,%.6f,%.6f" % (
                time.ticks_diff(now, t0),
                ax,
                ay,
                az,
                temp,
                gx,
                gy,
                gz,
            )
            print(line)
            f.write(line + "\n")
            if n % SAMPLE_HZ == 0:
                f.flush()

            next_t = time.ticks_add(next_t, interval_ms)
            wait_ms = time.ticks_diff(next_t, time.ticks_ms())
            if wait_ms > 0:
                time.sleep_ms(wait_ms)

    print("done, saved to", OUTPUT_FILE)


main()
