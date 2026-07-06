"""
Run this file on the computer with Thonny's local Python interpreter.

This script captures long stationary IMU data for gyroscope bias and Allan
deviation analysis. It sends temporary MicroPython code to ESP32 RAM through
the serial port and saves all CSV data on the computer.

Nothing is saved to ESP32 flash.
"""

from pathlib import Path
from datetime import datetime
import serial
import time


COM_PORT = "COM7"  # Change this to your ESP32 port if needed.
BAUDRATE = 115200

SAMPLE_HZ = 50
DURATION_S = 1800  # 30 min recommended for Allan deviation. Use 600 for a quick 10 min run.


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


REMOTE_GYRO_ALLAN_CODE = r'''
from machine import Pin, I2C
import time
import struct

try:
    import network
except Exception:
    network = None

SDA_PIN = 21
SCL_PIN = 22
I2C_FREQ = 400000
MPU_ADDR = 0x68
SAMPLE_HZ = __SAMPLE_HZ__
DURATION_S = __DURATION_S__

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
    # DLPF_CFG=3, about 44 Hz gyro bandwidth on MPU6050-compatible devices.
    i2c.writeto_mem(MPU_ADDR, 0x1A, b"\x03")
    # Gyro full scale: +/-250 dps.
    i2c.writeto_mem(MPU_ADDR, 0x1B, b"\x00")
    # Accel full scale: +/-2 g, kept for vibration/reference check.
    i2c.writeto_mem(MPU_ADDR, 0x1C, b"\x00")
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

wifi_off()
i2c = I2C(0, sda=Pin(SDA_PIN), scl=Pin(SCL_PIN), freq=I2C_FREQ)
scan = i2c.scan()
if MPU_ADDR not in scan:
    print("GYRO_ALLAN_ERROR,no_0x68,scan=" + ",".join(hex(x) for x in scan))
else:
    init_imu(i2c)
    print("BEGIN_GYRO_ALLAN_CSV")
    print("# purpose,gyroscope bias and Allan deviation")
    print("# sample_hz,%d" % SAMPLE_HZ)
    print("# duration_s,%d" % DURATION_S)
    print("# sda_gpio,%d" % SDA_PIN)
    print("# scl_gpio,%d" % SCL_PIN)
    print("# i2c_freq,%d" % I2C_FREQ)
    print("# gyro_full_scale,+-250 dps")
    print("# accel_full_scale,+-2 g")
    print("# dlpf_cfg,3")
    print("# wifi,off")
    print("# note,keep the board completely still")
    print("t_ms,ax_g,ay_g,az_g,temp_c,gx_dps,gy_dps,gz_dps")

    interval_ms = int(1000 / SAMPLE_HZ)
    total = SAMPLE_HZ * DURATION_S
    t0 = time.ticks_ms()
    next_t = t0

    for n in range(total):
        now = time.ticks_ms()
        ax, ay, az, temp, gx, gy, gz = read_imu(i2c)
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

    print("END_GYRO_ALLAN_CSV")
'''


def make_remote_code():
    return (
        REMOTE_GYRO_ALLAN_CODE.replace("__SAMPLE_HZ__", str(SAMPLE_HZ))
        .replace("__DURATION_S__", str(DURATION_S))
    )


def capture_csv(ser, output_path):
    in_csv = False
    rows = []
    last_progress = -1
    end_time = time.time() + DURATION_S + 90

    while time.time() < end_time:
        line = ser.readline().decode("utf-8", errors="replace").strip()
        if not line:
            continue

        if line.startswith("GYRO_ALLAN_ERROR"):
            raise RuntimeError(line)

        if line == "BEGIN_GYRO_ALLAN_CSV":
            in_csv = True
            print("Capture started. Do not touch the board.")
            continue

        if line == "END_GYRO_ALLAN_CSV":
            output_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
            return len(rows)

        if in_csv:
            rows.append(line)
            if not line.startswith("#") and not line.startswith("t_ms"):
                try:
                    elapsed_s = int(line.split(",", 1)[0]) // 1000
                except Exception:
                    continue
                progress = elapsed_s // 30
                if progress != last_progress:
                    pct = 100.0 * elapsed_s / DURATION_S
                    print("  progress: %d/%d s (%.1f%%)" % (elapsed_s, DURATION_S, pct))
                    last_progress = progress
            continue

        print(line)

    raise TimeoutError("Capture timed out before END_GYRO_ALLAN_CSV.")


def write_notes(notes_path, csv_path, timestamp):
    text = """Gyroscope bias and Allan deviation capture
timestamp: {timestamp}
csv: {csv_name}
sample_hz: {sample_hz}
duration_s: {duration_s}
i2c: SDA=GPIO21, SCL=GPIO22
gyro_range: +/-250 dps
dlpf_cfg: 3
wifi: off during capture

Physical experiment record:
1. Keep the ESP32 expansion board completely still for the whole capture.
2. Fix the board on a stable desk using tape, foam, paper box, or other non-magnetic support.
3. Keep away from vibration sources such as fans, tapping the desk, moving laptops, and motors.
4. Do not touch the USB cable or board after pressing Enter.
5. Keep the environment temperature as stable as possible.
6. If the board is moved during capture, repeat the experiment.

Report figures to generate later:
1. Gyroscope three-axis output over time.
2. Gyroscope zero-bias histogram.
3. Gyroscope Allan deviation curves.
4. Bias and noise statistics table.
""".format(
        timestamp=timestamp,
        csv_name=csv_path.name,
        sample_hz=SAMPLE_HZ,
        duration_s=DURATION_S,
    )
    notes_path.write_text(text, encoding="utf-8")


def main():
    data_dir = Path(__file__).resolve().parent / "data" / "gyro_allan"
    data_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = data_dir / ("gyro_allan_%s.csv" % timestamp)
    notes_path = data_dir / ("gyro_allan_%s_notes.txt" % timestamp)

    print("Gyroscope bias and Allan deviation capture")
    print("Port:", COM_PORT)
    print("Duration: %d s (%.1f min) at %d Hz" % (DURATION_S, DURATION_S / 60.0, SAMPLE_HZ))
    print("Output CSV:", output_path)
    print("")
    print("Before starting:")
    print("  1. Fix the board completely still on the desk.")
    print("  2. Keep the USB cable relaxed; do not touch it during capture.")
    print("  3. Move fans, phones, motors, and metal tools away from the board.")
    print("  4. Do not type hard, knock the desk, or move the computer during capture.")
    print("")
    input("Press Enter to start the stationary capture...")

    with serial.Serial(COM_PORT, BAUDRATE, timeout=1) as ser:
        start_remote_code(ser, make_remote_code())
        row_count = capture_csv(ser, output_path)
        exit_raw_repl(ser)

    write_notes(notes_path, output_path, timestamp)
    print("")
    print("Saved %d CSV lines to: %s" % (row_count, output_path))
    print("Saved experiment notes to: %s" % notes_path)
    print("Next step: run Allan deviation analysis on this CSV.")


if __name__ == "__main__":
    main()
