from machine import Pin, I2C
import time
import struct


SDA_PIN = 21
SCL_PIN = 22
I2C_FREQ = 100000

MPU6050_ADDR = 0x68
HMC5883L_ADDR = 0x1E
BMP_ADDR = 0x76


def read_i16_be(i2c, addr, reg):
    data = i2c.readfrom_mem(addr, reg, 2)
    return struct.unpack(">h", data)[0]


def init_mpu6050(i2c):
    who = i2c.readfrom_mem(MPU6050_ADDR, 0x75, 1)[0]
    i2c.writeto_mem(MPU6050_ADDR, 0x6B, b"\x00")  # Wake up.
    time.sleep_ms(100)
    i2c.writeto_mem(MPU6050_ADDR, 0x1B, b"\x00")  # Gyro +/-250 dps.
    i2c.writeto_mem(MPU6050_ADDR, 0x1C, b"\x00")  # Accel +/-2 g.
    return who


def read_mpu6050(i2c):
    raw = i2c.readfrom_mem(MPU6050_ADDR, 0x3B, 14)
    ax, ay, az, temp, gx, gy, gz = struct.unpack(">hhhhhhh", raw)
    return {
        "ax_g": ax / 16384.0,
        "ay_g": ay / 16384.0,
        "az_g": az / 16384.0,
        "temp_c": temp / 340.0 + 36.53,
        "gx_dps": gx / 131.0,
        "gy_dps": gy / 131.0,
        "gz_dps": gz / 131.0,
    }


def init_hmc5883l(i2c):
    i2c.writeto_mem(HMC5883L_ADDR, 0x00, b"\x70")  # 8 samples, 15 Hz.
    i2c.writeto_mem(HMC5883L_ADDR, 0x01, b"\x20")  # Gain +/-1.3 gauss.
    i2c.writeto_mem(HMC5883L_ADDR, 0x02, b"\x00")  # Continuous mode.
    time.sleep_ms(100)


def read_hmc5883l(i2c):
    raw = i2c.readfrom_mem(HMC5883L_ADDR, 0x03, 6)
    x, z, y = struct.unpack(">hhh", raw)
    return {"mx": x, "my": y, "mz": z}


def read_bmp_id(i2c):
    try:
        chip_id = i2c.readfrom_mem(BMP_ADDR, 0xD0, 1)[0]
        return chip_id
    except Exception as exc:
        print("BMP/MS5611 ID read failed:", exc)
        return None


def main():
    print("Sensor smoke test")
    print("I2C: SDA=GPIO%d, SCL=GPIO%d" % (SDA_PIN, SCL_PIN))

    i2c = I2C(0, sda=Pin(SDA_PIN), scl=Pin(SCL_PIN), freq=I2C_FREQ)
    print("scan:", ["0x%02X" % a for a in i2c.scan()])

    print("\nMPU6050")
    who = init_mpu6050(i2c)
    print("WHO_AM_I = 0x%02X, expected 0x68" % who)

    print("\nHMC5883L")
    init_hmc5883l(i2c)
    print("configured continuous measurement mode")

    print("\nBMP/MS5611/BME280 at 0x76")
    chip_id = read_bmp_id(i2c)
    if chip_id is not None:
        print("chip id register 0xD0 = 0x%02X" % chip_id)
        print("BMP280 usually 0x58, BME280 usually 0x60. MS5611 may not use this ID register.")

    print("\nLive data. Move/tilt the board gently.")
    for n in range(20):
        mpu = read_mpu6050(i2c)
        mag = read_hmc5883l(i2c)
        print(
            "%02d  ACC(g) %.3f %.3f %.3f  GYRO(dps) %.2f %.2f %.2f  TEMP %.1fC  MAG %d %d %d"
            % (
                n,
                mpu["ax_g"],
                mpu["ay_g"],
                mpu["az_g"],
                mpu["gx_dps"],
                mpu["gy_dps"],
                mpu["gz_dps"],
                mpu["temp_c"],
                mag["mx"],
                mag["my"],
                mag["mz"],
            )
        )
        time.sleep_ms(500)

    print("\nDone.")


main()
