"""
Axis mapping verification for the ESP32 sensor board.

Run this file on the computer with Thonny's local Python interpreter.
It sends temporary MicroPython code to ESP32 RAM, then captures IMU and
magnetometer data for several known board poses. CSV files are saved on the PC.
Nothing is saved to the ESP32 flash.
"""

from pathlib import Path
from datetime import datetime
import csv
import serial
import time


COM_PORT = "COM7"
BAUDRATE = 115200

SAMPLE_HZ = 50
STATIC_DURATION_S = 10
ROTATION_DURATION_S = 8
HEADING_DURATION_S = 10

BASE_DIR = Path(__file__).resolve().parents[2]
OUT_DIR = BASE_DIR / "data" / "calibration" / "axis_mapping"


POSES = [
    ("static_pos_x_up", STATIC_DURATION_S, "Make +X_body point upward and keep still."),
    ("static_neg_x_up", STATIC_DURATION_S, "Make -X_body point upward and keep still."),
    ("static_pos_y_up", STATIC_DURATION_S, "Make +Y_body point upward and keep still."),
    ("static_neg_y_up", STATIC_DURATION_S, "Make -Y_body point upward and keep still."),
    ("static_pos_z_up", STATIC_DURATION_S, "Make +Z_body point upward and keep still."),
    ("static_neg_z_up", STATIC_DURATION_S, "Make -Z_body point upward and keep still."),
    ("rotate_positive_roll_x", ROTATION_DURATION_S, "Rotate mainly around +X_body by hand."),
    ("rotate_positive_pitch_y", ROTATION_DURATION_S, "Rotate mainly around +Y_body by hand."),
    ("rotate_positive_yaw_z", ROTATION_DURATION_S, "Keep level and rotate mainly around +Z_body."),
    ("heading_x_forward", HEADING_DURATION_S, "Keep level. Point +X_body to a fixed direction."),
    ("heading_y_forward", HEADING_DURATION_S, "Keep level. Rotate 90 deg so +Y_body points to the same direction."),
    ("heading_neg_x_forward", HEADING_DURATION_S, "Keep level. Rotate 180 deg so -X_body points to the same direction."),
    ("heading_neg_y_forward", HEADING_DURATION_S, "Keep level. Rotate 270 deg so -Y_body points to the same direction."),
]


REMOTE_CODE = r'''
from machine import Pin, I2C
import time
import struct

SDA_PIN = 21
SCL_PIN = 22
I2C_FREQ = 400000
MPU_ADDR = 0x68
MAG_ADDR = 0x1E
SAMPLE_HZ = __SAMPLE_HZ__
DURATION_S = __DURATION_S__
LABEL = "__LABEL__"

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

def s16(v):
    return v - 65536 if v > 32767 else v

def read_imu(i2c):
    raw = i2c.readfrom_mem(MPU_ADDR, 0x3B, 14)
    ax, ay, az, temp, gx, gy, gz = struct.unpack(">hhhhhhh", raw)
    return ax / 16384.0, ay / 16384.0, az / 16384.0, temp / 340.0 + 36.53, gx / 131.0, gy / 131.0, gz / 131.0

def read_mag(i2c):
    raw = i2c.readfrom_mem(MAG_ADDR, 0x03, 6)
    x, z, y = struct.unpack(">hhh", raw)
    return x, y, z

i2c = I2C(0, sda=Pin(SDA_PIN), scl=Pin(SCL_PIN), freq=I2C_FREQ)
scan = i2c.scan()
print("# purpose,axis mapping verification")
print("# label," + LABEL)
print("# scan," + ",".join(hex(x) for x in scan))
print("# sample_hz,%d" % SAMPLE_HZ)
print("# duration_s,%d" % DURATION_S)

if MPU_ADDR not in scan:
    print("AXIS_VERIFY_ERROR,no_imu")
else:
    init_imu(i2c)
    has_mag = MAG_ADDR in scan
    if has_mag:
        init_mag(i2c)
    else:
        print("# warning,no_hmc5883l")
    print("t_ms,label,ax_g,ay_g,az_g,temp_c,gx_dps,gy_dps,gz_dps,mx_raw,my_raw,mz_raw")
    t0 = time.ticks_ms()
    period = int(1000 / SAMPLE_HZ)
    next_t = t0
    while time.ticks_diff(time.ticks_ms(), t0) < DURATION_S * 1000:
        now = time.ticks_ms()
        if time.ticks_diff(now, next_t) >= 0:
            ax, ay, az, temp, gx, gy, gz = read_imu(i2c)
            if has_mag:
                mx, my, mz = read_mag(i2c)
            else:
                mx, my, mz = 0, 0, 0
            print("%d,%s,%.6f,%.6f,%.6f,%.3f,%.6f,%.6f,%.6f,%d,%d,%d" %
                  (time.ticks_diff(now, t0), LABEL, ax, ay, az, temp, gx, gy, gz, mx, my, mz))
            next_t = time.ticks_add(next_t, period)
'''


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


def capture_pose(ser, label, duration_s):
    code = REMOTE_CODE.replace("__SAMPLE_HZ__", str(SAMPLE_HZ))
    code = code.replace("__DURATION_S__", str(duration_s))
    code = code.replace("__LABEL__", label)
    start_remote_code(ser, code)

    rows = []
    notes = []
    header = None
    deadline = time.time() + duration_s + 8
    while time.time() < deadline:
        raw = ser.readline()
        if not raw:
            continue
        line = raw.decode("utf-8", "replace").strip()
        if not line:
            continue
        print(line)
        if line.startswith("#"):
            notes.append(line)
            continue
        if line.startswith("AXIS_VERIFY_ERROR"):
            raise RuntimeError(line)
        if line.startswith("t_ms,"):
            header = line.split(",")
            continue
        if header:
            parts = line.split(",")
            if len(parts) == len(header):
                rows.append(parts)
        if rows and float(rows[-1][0]) >= duration_s * 1000 - 100:
            break
    return notes, header, rows


def save_csv(path, notes, header, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        for note in notes:
            f.write(note + "\n")
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    print("Axis mapping verification")
    print("Output:", OUT_DIR)
    print("COM:", COM_PORT)
    print()
    print("Important: use one fixed board/body definition for all poses.")
    print("Recommended: +X_body forward, +Y_body left, +Z_body up from PCB front side.")
    print()

    with serial.Serial(COM_PORT, BAUDRATE, timeout=1) as ser:
        time.sleep(2)
        ser.reset_input_buffer()
        for idx, (label, duration_s, prompt) in enumerate(POSES, start=1):
            print()
            print("[%02d/%02d] %s" % (idx, len(POSES), label))
            print(prompt)
            input("Press Enter when the board is ready...")
            notes, header, rows = capture_pose(ser, label, duration_s)
            out = OUT_DIR / ("%s_%s.csv" % (label, stamp))
            save_csv(out, notes, header, rows)
            print("Saved:", out)
        exit_raw_repl(ser)

    print()
    print("Done. Next run analyze_axis_mapping_verify.py.")


if __name__ == "__main__":
    main()
