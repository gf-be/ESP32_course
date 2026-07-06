"""
Run this file on the computer with Thonny's local Python interpreter.

The script sends temporary MicroPython code to the ESP32 RAM, reads IMU samples
through the serial port, and saves the CSV on the computer beside this file.
Nothing is saved to the ESP32 flash.
"""

from pathlib import Path
from datetime import datetime
import serial
import time


COM_PORT = "COM7"  # Change this to your ESP32 port, for example COM3/COM5/COM8.
BAUDRATE = 115200

SAMPLE_HZ = 50
DURATION_S = 120


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
        ser.write(data[i : i + 128])
        time.sleep(0.01)
    ser.write(b"\x04")
    read_until(ser, b"OK", timeout=5)


REMOTE_IMU_CODE = r'''
from machine import Pin, I2C
import time
import struct

SDA_PIN = 21
SCL_PIN = 22
I2C_FREQ = 400000
MPU_ADDR = 0x68
SAMPLE_HZ = __SAMPLE_HZ__
DURATION_S = __DURATION_S__

def init_mpu6050(i2c):
    i2c.writeto_mem(MPU_ADDR, 0x6B, b"\x00")
    time.sleep_ms(100)
    i2c.writeto_mem(MPU_ADDR, 0x1A, b"\x03")
    i2c.writeto_mem(MPU_ADDR, 0x1B, b"\x00")
    i2c.writeto_mem(MPU_ADDR, 0x1C, b"\x00")
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

i2c = I2C(0, sda=Pin(SDA_PIN), scl=Pin(SCL_PIN), freq=I2C_FREQ)
init_mpu6050(i2c)

print("BEGIN_IMU_STATIC_CSV")
print("# sample_hz,%d" % SAMPLE_HZ)
print("# duration_s,%d" % DURATION_S)
print("# sda_gpio,%d" % SDA_PIN)
print("# scl_gpio,%d" % SCL_PIN)
print("t_ms,ax_g,ay_g,az_g,temp_c,gx_dps,gy_dps,gz_dps")

interval_ms = int(1000 / SAMPLE_HZ)
total = SAMPLE_HZ * DURATION_S
t0 = time.ticks_ms()
next_t = t0

for n in range(total):
    now = time.ticks_ms()
    ax, ay, az, temp, gx, gy, gz = read_mpu6050(i2c)
    print("%d,%.6f,%.6f,%.6f,%.3f,%.6f,%.6f,%.6f" % (
        time.ticks_diff(now, t0),
        ax,
        ay,
        az,
        temp,
        gx,
        gy,
        gz,
    ))
    next_t = time.ticks_add(next_t, interval_ms)
    wait_ms = time.ticks_diff(next_t, time.ticks_ms())
    if wait_ms > 0:
        time.sleep_ms(wait_ms)

print("END_IMU_STATIC_CSV")
'''


def make_remote_code():
    return (
        REMOTE_IMU_CODE.replace("__SAMPLE_HZ__", str(SAMPLE_HZ))
        .replace("__DURATION_S__", str(DURATION_S))
    )


def capture_csv(ser, output_path):
    in_csv = False
    rows = []
    expected_timeout = DURATION_S + 30
    end_time = time.time() + expected_timeout

    while time.time() < end_time:
        line = ser.readline().decode("utf-8", errors="replace").strip()
        if not line:
            continue
        print(line)
        if line == "BEGIN_IMU_STATIC_CSV":
            in_csv = True
            continue
        if line == "END_IMU_STATIC_CSV":
            output_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
            return len(rows)
        if in_csv:
            rows.append(line)

    raise TimeoutError("Capture timed out before END_IMU_STATIC_CSV.")


def main():
    data_dir = Path(__file__).resolve().parent / "data"
    data_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = data_dir / ("imu_static_120s_%s.csv" % timestamp)

    print("Connecting to", COM_PORT)
    print("Keep the board completely still for %d seconds." % DURATION_S)
    with serial.Serial(COM_PORT, BAUDRATE, timeout=1) as ser:
        start_remote_code(ser, make_remote_code())
        row_count = capture_csv(ser, output_path)
        exit_raw_repl(ser)

    print("Saved %d CSV lines to: %s" % (row_count, output_path))


if __name__ == "__main__":
    main()
