"""
ESP32 MicroPython real-time attitude demo.

This file is intended to be copied to ESP32 as main.py for a live demo.
It reads IMU + magnetometer data and runs a complementary attitude filter.

Pins used in current experiments:
  I2C SDA = GPIO21
  I2C SCL = GPIO22
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
ALPHA = 0.98

GYRO_BIAS_X = 0.228303741
GYRO_BIAS_Y = 0.964654373
GYRO_BIAS_Z = -0.100939275


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
    return x - 77.082135, y + 94.427834, z + 36.852085


def wrap_deg(x):
    while x > 180:
        x -= 360
    while x < -180:
        x += 360
    return x


def accel_angles(ax, ay, az):
    roll = math.atan2(ay, az) * 57.2957795
    pitch = math.atan2(-ax, math.sqrt(ay * ay + az * az)) * 57.2957795
    return roll, pitch


def mag_yaw(mx, my, mz, roll_deg, pitch_deg):
    roll = roll_deg / 57.2957795
    pitch = pitch_deg / 57.2957795
    mx2 = mx * math.cos(pitch) + mz * math.sin(pitch)
    my2 = (
        mx * math.sin(roll) * math.sin(pitch)
        + my * math.cos(roll)
        - mz * math.sin(roll) * math.cos(pitch)
    )
    return math.atan2(-my2, mx2) * 57.2957795


def main():
    i2c = I2C(0, sda=Pin(SDA_PIN), scl=Pin(SCL_PIN), freq=I2C_FREQ)
    scan = i2c.scan()
    if MPU_ADDR not in scan:
        print("IMU not found; scan =", [hex(x) for x in scan])
        return
    init_imu(i2c)
    has_mag = MAG_ADDR in scan
    if has_mag:
        init_mag(i2c)

    roll = 0.0
    pitch = 0.0
    yaw = 0.0
    interval_ms = int(1000 / TARGET_HZ)
    last = time.ticks_ms()
    next_t = last
    count = 0
    fps_t0 = last

    print("t_ms,roll_deg,pitch_deg,yaw_deg,temp_c,update_hz")
    while True:
        now = time.ticks_ms()
        dt = max(0.001, time.ticks_diff(now, last) / 1000.0)
        last = now

        ax, ay, az, temp, gx, gy, gz = read_imu(i2c)
        ar, ap = accel_angles(ax, ay, az)
        if has_mag:
            mx, my, mz = read_mag(i2c)
            myaw = mag_yaw(mx, my, mz, ar, ap)
        else:
            myaw = yaw

        roll = ALPHA * (roll + gx * dt) + (1.0 - ALPHA) * ar
        pitch = ALPHA * (pitch + gy * dt) + (1.0 - ALPHA) * ap
        yaw_pred = yaw + gz * dt
        yaw = wrap_deg(yaw_pred + (1.0 - ALPHA) * wrap_deg(myaw - yaw_pred))

        count += 1
        elapsed = time.ticks_diff(now, fps_t0)
        update_hz = 0.0
        if elapsed >= 1000:
            update_hz = count * 1000.0 / elapsed
            count = 0
            fps_t0 = now

        print("%d,%.3f,%.3f,%.3f,%.2f,%.2f" % (now, roll, pitch, yaw, temp, update_hz))

        next_t = time.ticks_add(next_t, interval_ms)
        wait_ms = time.ticks_diff(next_t, time.ticks_ms())
        if wait_ms > 0:
            time.sleep_ms(wait_ms)


main()

