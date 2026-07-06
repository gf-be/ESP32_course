"""
Run this file on the computer with Thonny's local Python interpreter.

It captures 3D magnetometer data for ellipsoid calibration. The script sends
temporary MicroPython code to the ESP32 through the serial port and saves the
CSV on the computer. Nothing is saved to the ESP32 flash.
"""

from pathlib import Path
from datetime import datetime
import serial
import time


COM_PORT = "COM7"  # Change this to your ESP32 port.
BAUDRATE = 115200

SAMPLE_HZ = 20
DURATION_S = 180

PHASE_HINTS = [
    (0, "start: slow full-space rotation, keep away from metal"),
    (30, "phase 1: rotate around the board X direction"),
    (60, "phase 2: rotate around the board Y direction"),
    (90, "phase 3: rotate around the board Z direction"),
    (120, "phase 4: random 3D tumbling, cover tilted directions"),
    (150, "phase 5: slow figure-eight motion, fill missing orientations"),
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


REMOTE_MAG_ELLIPSOID_CODE = r'''
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
MAG_ADDR = 0x1E
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

def init_hmc5883l(i2c):
    # 8-sample average, 15 Hz nominal output, normal measurement.
    i2c.writeto_mem(MAG_ADDR, 0x00, b"\x70")
    # Gain +/-1.3 gauss. Keep the same setting as previous experiments.
    i2c.writeto_mem(MAG_ADDR, 0x01, b"\x20")
    # Continuous measurement mode.
    i2c.writeto_mem(MAG_ADDR, 0x02, b"\x00")
    time.sleep_ms(100)

def read_mag(i2c):
    raw = i2c.readfrom_mem(MAG_ADDR, 0x03, 6)
    x, z, y = struct.unpack(">hhh", raw)
    return x, y, z

wifi_off()
i2c = I2C(0, sda=Pin(SDA_PIN), scl=Pin(SCL_PIN), freq=I2C_FREQ)
scan = i2c.scan()
if MAG_ADDR not in scan:
    print("MAG_ELLIPSOID_ERROR,no_0x1e,scan=" + ",".join(hex(x) for x in scan))
else:
    init_hmc5883l(i2c)
    print("BEGIN_MAG_ELLIPSOID_CSV")
    print("# sensor,HMC5883L")
    print("# purpose,magnetometer ellipsoid calibration")
    print("# sample_hz,%d" % SAMPLE_HZ)
    print("# duration_s,%d" % DURATION_S)
    print("# sda_gpio,%d" % SDA_PIN)
    print("# scl_gpio,%d" % SCL_PIN)
    print("# wifi,off")
    print("# note,move the board slowly through all 3D orientations")
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

    print("END_MAG_ELLIPSOID_CSV")
'''


def make_remote_code():
    return (
        REMOTE_MAG_ELLIPSOID_CODE.replace("__SAMPLE_HZ__", str(SAMPLE_HZ))
        .replace("__DURATION_S__", str(DURATION_S))
    )


def phase_for_elapsed(elapsed_s):
    current = PHASE_HINTS[0][1]
    for t0, hint in PHASE_HINTS:
        if elapsed_s >= t0:
            current = hint
    return current


def capture_csv(ser, output_path):
    in_csv = False
    rows = []
    last_hint = None
    last_progress = -1
    end_time = time.time() + DURATION_S + 45

    while time.time() < end_time:
        line = ser.readline().decode("utf-8", errors="replace").strip()
        if not line:
            continue

        if line.startswith("MAG_ELLIPSOID_ERROR"):
            raise RuntimeError(line)

        if line == "BEGIN_MAG_ELLIPSOID_CSV":
            in_csv = True
            print("Capture started. Move slowly and continuously.")
            continue

        if line == "END_MAG_ELLIPSOID_CSV":
            output_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
            return len(rows)

        if in_csv:
            rows.append(line)
            if not line.startswith("#") and not line.startswith("t_ms"):
                parts = line.split(",", 1)
                try:
                    elapsed_s = int(parts[0]) // 1000
                except Exception:
                    continue
                hint = phase_for_elapsed(elapsed_s)
                if hint != last_hint:
                    print("[%3d s] %s" % (elapsed_s, hint))
                    last_hint = hint
                progress = elapsed_s // 15
                if progress != last_progress:
                    print("  progress: %d/%d s" % (elapsed_s, DURATION_S))
                    last_progress = progress
            continue

        print(line)

    raise TimeoutError("Capture timed out before END_MAG_ELLIPSOID_CSV.")


def write_notes(notes_path, csv_path, timestamp):
    text = """Magnetometer ellipsoid calibration capture
timestamp: {timestamp}
csv: {csv_name}
sensor: HMC5883L/GY-273 at I2C address 0x1E
i2c: SDA=GPIO21, SCL=GPIO22
sample_hz: {sample_hz}
duration_s: {duration_s}
wifi: off during capture

Physical experiment record:
1. Keep the GY-273 board position unchanged relative to the ESP32 expansion board.
2. Keep the setup away from phones, laptop speakers, motors, screwdrivers, magnets, steel table legs, and power adapters.
3. Rotate slowly through all 3D orientations. Avoid only flat tabletop rotation.
4. Do not touch the magnetometer chip area with metal tools during capture.
5. If any axis appears clipped or the point cloud is very incomplete, repeat the capture.
""".format(
        timestamp=timestamp,
        csv_name=csv_path.name,
        sample_hz=SAMPLE_HZ,
        duration_s=DURATION_S,
    )
    notes_path.write_text(text, encoding="utf-8")


def main():
    data_dir = Path(__file__).resolve().parent / "data" / "mag_ellipsoid"
    data_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = data_dir / ("mag_ellipsoid_%s.csv" % timestamp)
    notes_path = data_dir / ("mag_ellipsoid_%s_notes.txt" % timestamp)

    print("Magnetometer ellipsoid calibration capture")
    print("Port:", COM_PORT)
    print("Duration: %d s at %d Hz" % (DURATION_S, SAMPLE_HZ))
    print("Output CSV:", output_path)
    print("")
    print("Before starting:")
    print("  1. Keep WiFi off and move metal objects away.")
    print("  2. Hold the whole board assembly, not the magnetometer chip.")
    print("  3. During capture, rotate slowly through all 3D orientations.")
    print("  4. Do not only spin it flat on the table; include upside-down and tilted poses.")
    print("")
    input("Press Enter to start the 3-minute capture...")

    with serial.Serial(COM_PORT, BAUDRATE, timeout=1) as ser:
        start_remote_code(ser, make_remote_code())
        row_count = capture_csv(ser, output_path)
        exit_raw_repl(ser)

    write_notes(notes_path, output_path, timestamp)
    print("")
    print("Saved %d CSV lines to: %s" % (row_count, output_path))
    print("Saved experiment notes to: %s" % notes_path)
    print("Next step: run ellipsoid analysis on this CSV.")


if __name__ == "__main__":
    main()
