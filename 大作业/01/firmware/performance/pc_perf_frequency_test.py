"""
Run this file on the computer with Thonny's local Python interpreter.

It measures practical sensor sampling and attitude-fusion loop frequency on
ESP32 through temporary MicroPython code. Nothing is saved to ESP32 flash.

Report targets:
  IMU sampling rate >= 200 Hz
  attitude fusion update rate >= 100 Hz
"""

from pathlib import Path
from datetime import datetime
import serial
import time


COM_PORT = "COM4"
BAUDRATE = 115200

TEST_DURATION_S = 10


def read_until(ser, marker, timeout=5):
    end = time.time() + timeout
    data = b""
    while time.time() < end:
        chunk = ser.read(1)
        if chunk:
            data += chunk
            if marker in data:
                return data
    raise TimeoutError("Timeout waiting for %r. Received: %r" % (marker, data[-200:]))


def enter_raw_repl(ser):
    ser.write(b"\x03\x03")
    time.sleep(0.2)
    ser.reset_input_buffer()
    ser.write(b"\x01")
    read_until(ser, b">", timeout=5)


def exit_raw_repl(ser):
    ser.write(b"\x02")
    time.sleep(0.2)


def start_remote_code(ser, code):
    enter_raw_repl(ser)
    data = code.encode("utf-8")
    for i in range(0, len(data), 128):
        ser.write(data[i:i + 128])
        time.sleep(0.01)
    ser.write(b"\x04")
    read_until(ser, b"OK", timeout=5)


REMOTE_CODE = r'''
from machine import Pin, I2C
import time
import struct
import math

SDA_PIN = 21
SCL_PIN = 22
I2C_FREQ = 400000
MPU_ADDR = 0x68
MAG_ADDR = 0x1E
DURATION_S = __DURATION_S__

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
    return ax / 16384.0, ay / 16384.0, az / 16384.0, gx / 131.0, gy / 131.0, gz / 131.0

def read_mag(i2c):
    raw = i2c.readfrom_mem(MAG_ADDR, 0x03, 6)
    x, z, y = struct.unpack(">hhh", raw)
    return x, y, z

def accel_angles(ax, ay, az):
    roll = math.atan2(ay, az) * 57.2957795
    pitch = math.atan2(-ax, math.sqrt(ay * ay + az * az)) * 57.2957795
    return roll, pitch

def mag_yaw(mx, my, mz, roll_deg, pitch_deg):
    roll = roll_deg / 57.2957795
    pitch = pitch_deg / 57.2957795
    mx2 = mx * math.cos(pitch) + mz * math.sin(pitch)
    my2 = mx * math.sin(roll) * math.sin(pitch) + my * math.cos(roll) - mz * math.sin(roll) * math.cos(pitch)
    return math.atan2(-my2, mx2) * 57.2957795

def wrap_deg(x):
    while x > 180:
        x -= 360
    while x < -180:
        x += 360
    return x

i2c = I2C(0, sda=Pin(SDA_PIN), scl=Pin(SCL_PIN), freq=I2C_FREQ)
scan = i2c.scan()
if MPU_ADDR not in scan:
    print("PERF_ERROR,no_0x68,scan=" + ",".join(hex(x) for x in scan))
else:
    init_imu(i2c)
    if MAG_ADDR in scan:
        init_mag(i2c)

    print("BEGIN_PERF_TEST")
    print("# duration_s,%d" % DURATION_S)
    print("# i2c_freq,%d" % I2C_FREQ)

    # Test 1: raw IMU read speed.
    t0 = time.ticks_ms()
    count = 0
    while time.ticks_diff(time.ticks_ms(), t0) < DURATION_S * 1000:
        read_imu(i2c)
        count += 1
    elapsed_ms = time.ticks_diff(time.ticks_ms(), t0)
    imu_hz = count * 1000.0 / elapsed_ms
    print("imu_read_count,%d" % count)
    print("imu_elapsed_ms,%d" % elapsed_ms)
    print("imu_sampling_rate_hz,%.3f" % imu_hz)

    # Test 2: complementary fusion loop speed.
    alpha = 0.98
    roll = 0.0
    pitch = 0.0
    yaw = 0.0
    last = time.ticks_ms()
    t0 = time.ticks_ms()
    count = 0
    while time.ticks_diff(time.ticks_ms(), t0) < DURATION_S * 1000:
        now = time.ticks_ms()
        dt = max(0.001, time.ticks_diff(now, last) / 1000.0)
        last = now
        ax, ay, az, gx, gy, gz = read_imu(i2c)
        ar, ap = accel_angles(ax, ay, az)
        if MAG_ADDR in scan:
            mx, my, mz = read_mag(i2c)
            myaw = mag_yaw(mx, my, mz, ar, ap)
        else:
            myaw = yaw
        roll = alpha * (roll + gx * dt) + (1.0 - alpha) * ar
        pitch = alpha * (pitch + gy * dt) + (1.0 - alpha) * ap
        yaw_pred = yaw + gz * dt
        yaw = wrap_deg(yaw_pred + (1.0 - alpha) * wrap_deg(myaw - yaw_pred))
        count += 1
    elapsed_ms = time.ticks_diff(time.ticks_ms(), t0)
    fusion_hz = count * 1000.0 / elapsed_ms
    print("fusion_update_count,%d" % count)
    print("fusion_elapsed_ms,%d" % elapsed_ms)
    print("fusion_update_rate_hz,%.3f" % fusion_hz)
    print("END_PERF_TEST")
'''


def make_remote_code():
    return REMOTE_CODE.replace("__DURATION_S__", str(TEST_DURATION_S))


def capture_results(ser):
    rows = []
    in_block = False
    end_time = time.time() + TEST_DURATION_S * 2 + 30
    while time.time() < end_time:
        line = ser.readline().decode("utf-8", errors="replace").strip()
        if not line:
            continue
        print(line)
        if line.startswith("PERF_ERROR"):
            raise RuntimeError(line)
        if line == "BEGIN_PERF_TEST":
            in_block = True
            continue
        if line == "END_PERF_TEST":
            return rows
        if in_block:
            rows.append(line)
    raise TimeoutError("Performance test timed out.")


def main():
    out_dir = Path(__file__).resolve().parent / "data" / "performance"
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / ("frequency_test_%s.csv" % timestamp)

    print("ESP32 frequency test")
    print("Port:", COM_PORT)
    print("Duration per test:", TEST_DURATION_S, "s")
    input("Keep the board connected and press Enter to start...")

    with serial.Serial(COM_PORT, BAUDRATE, timeout=1) as ser:
        start_remote_code(ser, make_remote_code())
        rows = capture_results(ser)
        exit_raw_repl(ser)

    parsed = []
    for line in rows:
        if line.startswith("#"):
            parsed.append(["meta", line[1:]])
        else:
            k, v = line.split(",", 1)
            parsed.append([k, v])
    with out_path.open("w", newline="", encoding="utf-8-sig") as f:
        f.write("item,value\n")
        for k, v in parsed:
            f.write("%s,%s\n" % (k, v))

    print("Saved:", out_path)
    print("Report criteria: IMU >= 200 Hz, fusion >= 100 Hz")


if __name__ == "__main__":
    main()
