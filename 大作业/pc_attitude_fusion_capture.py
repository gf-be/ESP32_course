
"""
Run this file on the computer with Thonny's local Python interpreter.

It captures raw IMU + magnetometer data for attitude fusion experiments.
The script sends temporary MicroPython code to ESP32 RAM through the serial
port and saves CSV files on the computer. Nothing is saved to ESP32 flash.
"""

from pathlib import Path
from datetime import datetime
import serial
import time


COM_PORT = "COM7"  # Change this to your ESP32 port if needed.
BAUDRATE = 115200

SAMPLE_HZ = 50

PHASES = [
    ("level_static", 60, "水平静止：板子固定水平放置，不要触碰。"),
    ("tilt_static", 60, "固定倾斜：用纸盒/书本垫出约 30 或 45 度，保持不动。"),
    ("shake_return_level", 90, "晃动后回水平：前 30 秒轻微晃动/倾斜，之后放回水平并保持静止。"),
    ("continuous_motion", 120, "连续旋转/手动倾斜：慢速做 roll/pitch/yaw 方向变化，动作连续但不要太快。"),
]


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


REMOTE_ATTITUDE_CAPTURE_CODE = r'''
from machine import Pin, I2C
import time
import struct

try:
    import network
except Exception:
    network = None

SDA_PIN = 21
SCL_PIN = 22
I2C_FREQ = 100000
MPU_ADDR = 0x68
MAG_ADDR = 0x1E
SAMPLE_HZ = __SAMPLE_HZ__
DURATION_S = __DURATION_S__
LABEL = "__LABEL__"

def wifi_off():
    if network is None:
        return
    for iface in (network.STA_IF, network.AP_IF):
        try:
            wlan = network.WLAN(iface)
            wlan.active(False)
        except Exception:
            pass

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
        gx / 131.0,
        gy / 131.0,
        gz / 131.0,
    )

def read_mag(i2c):
    raw = i2c.readfrom_mem(MAG_ADDR, 0x03, 6)
    x, z, y = struct.unpack(">hhh", raw)
    return x, y, z

wifi_off()
i2c = I2C(0, sda=Pin(SDA_PIN), scl=Pin(SCL_PIN), freq=I2C_FREQ)
scan = i2c.scan()
if MPU_ADDR not in scan or MAG_ADDR not in scan:
    print("ATTITUDE_CAPTURE_ERROR,scan=" + ",".join(hex(x) for x in scan))
else:
    init_imu(i2c)
    init_mag(i2c)
    print("BEGIN_ATTITUDE_CSV")
    print("# purpose,attitude fusion experiment")
    print("# label,%s" % LABEL)
    print("# sample_hz,%d" % SAMPLE_HZ)
    print("# duration_s,%d" % DURATION_S)
    print("# sda_gpio,%d" % SDA_PIN)
    print("# scl_gpio,%d" % SCL_PIN)
    print("# wifi,off")
    print("t_ms,label,ax_g,ay_g,az_g,temp_c,gx_dps,gy_dps,gz_dps,mx_raw,my_raw,mz_raw")

    interval_ms = int(1000 / SAMPLE_HZ)
    total = SAMPLE_HZ * DURATION_S
    t0 = time.ticks_ms()
    next_t = t0

    for n in range(total):
        now = time.ticks_ms()
        ax, ay, az, temp, gx, gy, gz = read_imu(i2c)
        mx, my, mz = read_mag(i2c)
        print("%d,%s,%.6f,%.6f,%.6f,%.3f,%.6f,%.6f,%.6f,%d,%d,%d" % (
            time.ticks_diff(now, t0),
            LABEL,
            ax, ay, az,
            temp,
            gx, gy, gz,
            mx, my, mz,
        ))
        next_t = time.ticks_add(next_t, interval_ms)
        wait_ms = time.ticks_diff(next_t, time.ticks_ms())
        if wait_ms > 0:
            time.sleep_ms(wait_ms)

    print("END_ATTITUDE_CSV")
'''


def make_remote_code(label, duration_s):
    return (
        REMOTE_ATTITUDE_CAPTURE_CODE
        .replace("__SAMPLE_HZ__", str(SAMPLE_HZ))
        .replace("__DURATION_S__", str(duration_s))
        .replace("__LABEL__", label)
    )


def capture_csv(ser, output_path, duration_s):
    in_csv = False
    rows = []
    last_progress = -1
    end_time = time.time() + duration_s + 45

    while time.time() < end_time:
        line = ser.readline().decode("utf-8", errors="replace").strip()
        if not line:
            continue
        if line.startswith("ATTITUDE_CAPTURE_ERROR"):
            raise RuntimeError(line)
        if line == "BEGIN_ATTITUDE_CSV":
            in_csv = True
            print("Capture started.")
            continue
        if line == "END_ATTITUDE_CSV":
            output_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
            return len(rows)
        if in_csv:
            rows.append(line)
            if not line.startswith("#") and not line.startswith("t_ms"):
                try:
                    elapsed_s = int(line.split(",", 1)[0]) // 1000
                except Exception:
                    continue
                progress = elapsed_s // 10
                if progress != last_progress:
                    print("  progress: %d/%d s" % (elapsed_s, duration_s))
                    last_progress = progress
            continue
        print(line)

    raise TimeoutError("Capture timed out before END_ATTITUDE_CSV.")


def write_notes(notes_path, timestamp, files):
    lines = [
        "Attitude fusion experiment capture",
        "timestamp: %s" % timestamp,
        "sample_hz: %d" % SAMPLE_HZ,
        "sensors: MPU-compatible IMU at 0x68, HMC5883L magnetometer at 0x1E",
        "wifi: off during capture",
        "",
        "CSV files:",
    ]
    for label, path in files:
        lines.append("%s: %s" % (label, path.name))
    lines.extend([
        "",
        "Physical experiment record:",
        "1. level_static: board fixed horizontally and completely still.",
        "2. tilt_static: board fixed at about 30 or 45 degrees and completely still.",
        "3. shake_return_level: move the board first, then return to horizontal and keep still.",
        "4. continuous_motion: manually tilt/rotate continuously and smoothly.",
        "",
        "Report outputs to generate next:",
        "1. roll/pitch/yaw time series for complementary filter and Mahony filter.",
        "2. static roll/pitch/yaw standard deviation table.",
        "3. dynamic response curve for shake-return and continuous-motion phases.",
        "4. algorithm update frequency statistics.",
    ])
    notes_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    data_dir = Path(__file__).resolve().parent / "data" / "attitude_fusion"
    data_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    saved = []

    print("Attitude fusion raw-data capture")
    print("Port:", COM_PORT)
    print("Sample rate: %d Hz" % SAMPLE_HZ)
    print("Output directory:", data_dir)
    print("")
    print("This experiment has four phases. The script will pause before each phase.")
    print("Run it once and follow the on-screen physical instructions.")
    input("Press Enter when the board and workspace are ready...")

    with serial.Serial(COM_PORT, BAUDRATE, timeout=1) as ser:
        for label, duration_s, instruction in PHASES:
            print("")
            print("Phase:", label)
            print("Duration: %d s" % duration_s)
            print("Instruction:", instruction)
            input("Press Enter to start this phase...")
            output_path = data_dir / ("attitude_%s_%s.csv" % (label, timestamp))
            start_remote_code(ser, make_remote_code(label, duration_s))
            row_count = capture_csv(ser, output_path, duration_s)
            exit_raw_repl(ser)
            saved.append((label, output_path))
            print("Saved %d lines to: %s" % (row_count, output_path))

    notes_path = data_dir / ("attitude_fusion_%s_notes.txt" % timestamp)
    write_notes(notes_path, timestamp, saved)
    print("")
    print("All phases complete.")
    print("Saved notes to:", notes_path)


if __name__ == "__main__":
    main()
