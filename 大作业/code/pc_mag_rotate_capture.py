"""
Run this file on the computer with Thonny's local Python interpreter.

It captures HMC5883L magnetometer rotation data from the ESP32 through the
serial port and saves the CSV on the computer. Nothing is saved to ESP32 flash.
"""

from pathlib import Path
from datetime import datetime
import serial
import time


COM_PORT = "COM7"  # Change this to your ESP32 port.
BAUDRATE = 115200

SAMPLE_HZ = 20
DURATION_S = 90


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


REMOTE_MAG_CODE = r'''
from machine import Pin, I2C
import time
import struct

SDA_PIN = 21
SCL_PIN = 22
I2C_FREQ = 100000
MAG_ADDR = 0x1E
SAMPLE_HZ = __SAMPLE_HZ__
DURATION_S = __DURATION_S__

def init_hmc5883l(i2c):
    i2c.writeto_mem(MAG_ADDR, 0x00, b"\x70")
    i2c.writeto_mem(MAG_ADDR, 0x01, b"\x20")
    i2c.writeto_mem(MAG_ADDR, 0x02, b"\x00")
    time.sleep_ms(100)

def read_mag(i2c):
    raw = i2c.readfrom_mem(MAG_ADDR, 0x03, 6)
    x, z, y = struct.unpack(">hhh", raw)
    return x, y, z

i2c = I2C(0, sda=Pin(SDA_PIN), scl=Pin(SCL_PIN), freq=I2C_FREQ)
init_hmc5883l(i2c)

print("BEGIN_MAG_ROTATE_CSV")
print("# sensor,HMC5883L")
print("# sample_hz,%d" % SAMPLE_HZ)
print("# duration_s,%d" % DURATION_S)
print("# sda_gpio,%d" % SDA_PIN)
print("# scl_gpio,%d" % SCL_PIN)
print("t_ms,mx_raw,my_raw,mz_raw")

interval_ms = int(1000 / SAMPLE_HZ)
total = SAMPLE_HZ * DURATION_S
t0 = time.ticks_ms()
next_t = t0

for n in range(total):
    now = time.ticks_ms()
    mx, my, mz = read_mag(i2c)
    print("%d,%d,%d,%d" % (time.ticks_diff(now, t0), mx, my, mz))
    next_t = time.ticks_add(next_t, interval_ms)
    wait_ms = time.ticks_diff(next_t, time.ticks_ms())
    if wait_ms > 0:
        time.sleep_ms(wait_ms)

print("END_MAG_ROTATE_CSV")
'''


def make_remote_code():
    return (
        REMOTE_MAG_CODE.replace("__SAMPLE_HZ__", str(SAMPLE_HZ))
        .replace("__DURATION_S__", str(DURATION_S))
    )


def capture_csv(ser, output_path):
    in_csv = False
    rows = []
    end_time = time.time() + DURATION_S + 30

    while time.time() < end_time:
        line = ser.readline().decode("utf-8", errors="replace").strip()
        if not line:
            continue
        print(line)
        if line == "BEGIN_MAG_ROTATE_CSV":
            in_csv = True
            continue
        if line == "END_MAG_ROTATE_CSV":
            output_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
            return len(rows)
        if in_csv:
            rows.append(line)

    raise TimeoutError("Capture timed out before END_MAG_ROTATE_CSV.")


def main():
    data_dir = Path(__file__).resolve().parent / "data" / "mag_rotate"
    data_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = data_dir / ("mag_rotate_%s.csv" % timestamp)

    print("Magnetometer rotation capture")
    print("Port:", COM_PORT)
    print("Duration: %d s at %d Hz" % (DURATION_S, SAMPLE_HZ))
    print("Move the board slowly through as many orientations as possible.")
    input("Keep away from phone, laptop speaker, motors, and steel tools. Press Enter to start...")

    with serial.Serial(COM_PORT, BAUDRATE, timeout=1) as ser:
        start_remote_code(ser, make_remote_code())
        row_count = capture_csv(ser, output_path)
        exit_raw_repl(ser)

    print("Saved %d CSV lines to: %s" % (row_count, output_path))


if __name__ == "__main__":
    main()
