"""
Run this file on the computer with Thonny's local Python interpreter.

It captures two stationary HMC5883L magnetometer datasets through the ESP32:
1) ESP32 WiFi off
2) ESP32 WiFi on, with repeated WiFi scans to create radio activity

The CSV files are saved on the computer. Nothing is saved to ESP32 flash.
"""

from pathlib import Path
from datetime import datetime
import serial
import time


COM_PORT = "COM7"  # Change this to your ESP32 port.
BAUDRATE = 115200

SAMPLE_HZ = 20
DURATION_S = 60


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


REMOTE_MAG_WIFI_CODE = r'''
from machine import Pin, I2C
import time
import struct
import network

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

def wifi_off():
    sta = network.WLAN(network.STA_IF)
    ap = network.WLAN(network.AP_IF)
    try:
        sta.active(False)
    except Exception:
        pass
    try:
        ap.active(False)
    except Exception:
        pass
    time.sleep_ms(800)
    return sta

def wifi_on():
    sta = network.WLAN(network.STA_IF)
    sta.active(True)
    time.sleep_ms(800)
    return sta

def capture(i2c, label, sta=None):
    print("BEGIN_MAG_WIFI_CSV,%s" % label)
    print("# label,%s" % label)
    print("# sample_hz,%d" % SAMPLE_HZ)
    print("# duration_s,%d" % DURATION_S)
    print("# sda_gpio,%d" % SDA_PIN)
    print("# scl_gpio,%d" % SCL_PIN)
    print("t_ms,mx_raw,my_raw,mz_raw,wifi_scan_count")

    interval_ms = int(1000 / SAMPLE_HZ)
    total = SAMPLE_HZ * DURATION_S
    t0 = time.ticks_ms()
    next_t = t0
    scan_count = 0
    next_scan_t = t0

    for n in range(total):
        now = time.ticks_ms()
        if sta is not None and time.ticks_diff(now, next_scan_t) >= 0:
            try:
                sta.scan()
                scan_count += 1
            except Exception:
                pass
            next_scan_t = time.ticks_add(time.ticks_ms(), 5000)

        mx, my, mz = read_mag(i2c)
        print("%d,%d,%d,%d,%d" % (time.ticks_diff(now, t0), mx, my, mz, scan_count))

        next_t = time.ticks_add(next_t, interval_ms)
        wait_ms = time.ticks_diff(next_t, time.ticks_ms())
        if wait_ms > 0:
            time.sleep_ms(wait_ms)

    print("END_MAG_WIFI_CSV,%s" % label)

i2c = I2C(0, sda=Pin(SDA_PIN), scl=Pin(SCL_PIN), freq=I2C_FREQ)
init_hmc5883l(i2c)

print("MAG_WIFI_COMPARE_READY")
wifi_off()
capture(i2c, "wifi_off", None)
sta = wifi_on()
capture(i2c, "wifi_on_scan", sta)
wifi_off()
print("MAG_WIFI_COMPARE_DONE")
'''


def make_remote_code():
    return (
        REMOTE_MAG_WIFI_CODE.replace("__SAMPLE_HZ__", str(SAMPLE_HZ))
        .replace("__DURATION_S__", str(DURATION_S))
    )


def capture_two_csvs(ser, out_dir, timestamp):
    active_label = None
    rows = []
    saved = []
    end_time = time.time() + DURATION_S * 2 + 90

    while time.time() < end_time:
        line = ser.readline().decode("utf-8", errors="replace").strip()
        if not line:
            continue
        print(line)

        if line.startswith("BEGIN_MAG_WIFI_CSV,"):
            active_label = line.split(",", 1)[1]
            rows = []
            continue

        if line.startswith("END_MAG_WIFI_CSV,"):
            label = line.split(",", 1)[1]
            if label != active_label:
                raise RuntimeError("CSV label mismatch: %s vs %s" % (active_label, label))
            output_path = out_dir / ("mag_%s_%s.csv" % (label, timestamp))
            output_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
            saved.append(output_path)
            active_label = None
            rows = []
            continue

        if line == "MAG_WIFI_COMPARE_DONE":
            return saved

        if active_label:
            rows.append(line)

    raise TimeoutError("Capture timed out before MAG_WIFI_COMPARE_DONE.")


def main():
    data_dir = Path(__file__).resolve().parent / "data" / "mag_wifi_compare"
    data_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    print("Magnetometer WiFi interference comparison")
    print("Port:", COM_PORT)
    print("Each condition: %d s at %d Hz" % (DURATION_S, SAMPLE_HZ))
    print("Keep the board completely still during both captures.")
    print("Move phones, magnets, screwdrivers, and steel tools away from the board.")
    input("Press Enter to start WiFi-off then WiFi-on comparison...")

    with serial.Serial(COM_PORT, BAUDRATE, timeout=1) as ser:
        start_remote_code(ser, make_remote_code())
        saved = capture_two_csvs(ser, data_dir, timestamp)
        exit_raw_repl(ser)

    print("Saved files:")
    for path in saved:
        print(" ", path)


if __name__ == "__main__":
    main()
