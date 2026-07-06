# -*- coding: utf-8 -*-
"""
PC-side synchronized IMU + GPS capture for the 15D ESKF experiment.

Run this file on the computer with Thonny's local Python interpreter. It sends
temporary MicroPython code to ESP32 RAM through the serial port and saves the
CSV on the computer. Nothing is saved to ESP32 flash.
"""

from pathlib import Path
from datetime import datetime
import serial
import time


COM_PORT = "COM4"  # Change if your ESP32 appears as another COM port.
BAUDRATE = 115200

SAMPLE_HZ = 50
DURATION_S = 900  # 15 minutes. Change to 600 for a shorter 10-minute walk.


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


REMOTE_SYNC_CAPTURE_CODE = r'''
from machine import Pin, I2C, UART
import math
import struct
import time

try:
    import network
except Exception:
    network = None

SDA_PIN = 21
SCL_PIN = 22
I2C_FREQ = 400000
MPU_ADDR = 0x68
MAG_ADDR = 0x1E

GPS_UART_ID = 2
GPS_RX_PIN = 16
GPS_TX_PIN = 17
GPS_BAUDRATE = 9600

SAMPLE_HZ = __SAMPLE_HZ__
DURATION_S = __DURATION_S__

QUALITY_MIN_SATS = 4
QUALITY_MAX_HDOP = 5.0

def wifi_off():
    if network is None:
        return
    for iface in (network.STA_IF, network.AP_IF):
        try:
            wlan = network.WLAN(iface)
            wlan.active(False)
        except Exception:
            pass

def nmea_checksum_ok(sentence):
    if "*" not in sentence:
        return True
    try:
        body, checksum = sentence[1:].split("*", 1)
        calc = 0
        for ch in body:
            calc ^= ord(ch)
        return calc == int(checksum[:2], 16)
    except Exception:
        return False

def parse_latlon(value, hemi):
    if not value:
        return None
    raw = float(value)
    deg = int(raw // 100)
    minutes = raw - deg * 100
    out = deg + minutes / 60.0
    if hemi == "S" or hemi == "W":
        out = -out
    return out

class GPSParser:
    def __init__(self):
        self.lat = 0.0
        self.lon = 0.0
        self.alt = 0.0
        self.sats = 0
        self.hdop = 99.0
        self.fix_quality = 0
        self.valid = False
        self.usable = False
        self.utc = ""
        self.date = ""
        self.speed_mps = 0.0
        self.course_deg = float("nan")
        self.last_fix_ms = -1000000
        self.nmea_count = 0
        self.fix_count = 0
        self.checksum_fail_count = 0
        self.line_buf = ""
        self.updated = 0

    def feed(self, line, now_ms):
        if not line or not line.startswith("$"):
            return False
        self.nmea_count += 1
        if not nmea_checksum_ok(line):
            self.checksum_fail_count += 1
            return False
        parts = line.split("*", 1)[0].split(",")
        typ = parts[0]
        changed = False
        try:
            if typ.endswith("RMC") and len(parts) >= 10:
                self.utc = parts[1]
                self.date = parts[9]
                if parts[2] == "A":
                    lat = parse_latlon(parts[3], parts[4])
                    lon = parse_latlon(parts[5], parts[6])
                    if lat is not None and lon is not None:
                        self.lat = lat
                        self.lon = lon
                        self.speed_mps = float(parts[7]) * 0.514444 if parts[7] else 0.0
                        self.course_deg = float(parts[8]) if parts[8] else float("nan")
                        self.valid = True
                        changed = True
            elif typ.endswith("GGA") and len(parts) >= 10:
                self.utc = parts[1]
                q = int(parts[6]) if parts[6] else 0
                self.fix_quality = q
                self.sats = int(parts[7]) if parts[7] else 0
                self.hdop = float(parts[8]) if parts[8] else 99.0
                if q > 0:
                    lat = parse_latlon(parts[2], parts[3])
                    lon = parse_latlon(parts[4], parts[5])
                    if lat is not None and lon is not None:
                        self.lat = lat
                        self.lon = lon
                        self.alt = float(parts[9]) if parts[9] else 0.0
                        self.valid = True
                        self.last_fix_ms = now_ms
                        self.fix_count += 1
                        changed = True
        except Exception:
            return False
        self.usable = self.valid and self.fix_quality > 0 and self.sats >= QUALITY_MIN_SATS and self.hdop <= QUALITY_MAX_HDOP
        if changed:
            self.updated = 1
        return changed

def read_gps_lines(uart, parser, now_ms):
    got = False
    loops = 0
    while uart.any() and loops < 8:
        loops += 1
        n = uart.any()
        if n > 128:
            n = 128
        raw = uart.read(n)
        if not raw:
            continue
        try:
            parser.line_buf += raw.decode("ascii")
        except Exception:
            continue
        if len(parser.line_buf) > 512:
            parser.line_buf = parser.line_buf[-512:]

    line_count = 0
    while "\n" in parser.line_buf and line_count < 12:
        line_count += 1
        line, parser.line_buf = parser.line_buf.split("\n", 1)
        if parser.feed(line.strip(), now_ms):
            got = True
    return got

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
    print("SYNC_CAPTURE_ERROR,scan=" + ",".join(hex(x) for x in scan))
else:
    init_imu(i2c)
    init_mag(i2c)
    uart = UART(
        GPS_UART_ID,
        baudrate=GPS_BAUDRATE,
        bits=8,
        parity=None,
        stop=1,
        rx=Pin(GPS_RX_PIN),
        tx=Pin(GPS_TX_PIN),
        timeout=0,
    )
    gps = GPSParser()

    print("BEGIN_IMU_GPS_SYNC_CSV")
    print("# purpose,synchronized IMU GPS data for 15D ESKF")
    print("# sample_hz,%d" % SAMPLE_HZ)
    print("# duration_s,%d" % DURATION_S)
    print("# i2c_sda_gpio,%d" % SDA_PIN)
    print("# i2c_scl_gpio,%d" % SCL_PIN)
    print("# gps_uart_rx_gpio,%d" % GPS_RX_PIN)
    print("# gps_uart_tx_gpio,%d" % GPS_TX_PIN)
    print("# wifi,off")
    print("t_ms,ax_g,ay_g,az_g,temp_c,gx_dps,gy_dps,gz_dps,mx_raw,my_raw,mz_raw,gps_updated,gps_valid,gps_usable,fix_quality,satellites,hdop,gps_lat,gps_lon,gps_alt_m,gps_speed_mps,gps_course_deg,gps_utc,gps_date,nmea_count,fix_count,checksum_fail_count")

    interval_ms = int(1000 / SAMPLE_HZ)
    total = SAMPLE_HZ * DURATION_S
    t0 = time.ticks_ms()
    next_t = t0
    for _ in range(total):
        now = time.ticks_ms()
        gps.updated = 0
        read_gps_lines(uart, gps, now)
        ax, ay, az, temp, gx, gy, gz = read_imu(i2c)
        mx, my, mz = read_mag(i2c)
        print("%d,%.6f,%.6f,%.6f,%.3f,%.6f,%.6f,%.6f,%d,%d,%d,%d,%d,%d,%d,%d,%.2f,%.8f,%.8f,%.2f,%.3f,%.2f,%s,%s,%d,%d,%d" % (
            time.ticks_diff(now, t0),
            ax, ay, az, temp, gx, gy, gz,
            mx, my, mz,
            gps.updated,
            1 if gps.valid else 0,
            1 if gps.usable else 0,
            gps.fix_quality,
            gps.sats,
            gps.hdop,
            gps.lat,
            gps.lon,
            gps.alt,
            gps.speed_mps,
            gps.course_deg,
            gps.utc,
            gps.date,
            gps.nmea_count,
            gps.fix_count,
            gps.checksum_fail_count,
        ))
        next_t = time.ticks_add(next_t, interval_ms)
        wait_ms = time.ticks_diff(next_t, time.ticks_ms())
        if wait_ms > 0:
            time.sleep_ms(wait_ms)

    print("END_IMU_GPS_SYNC_CSV")
'''


def make_remote_code():
    return (
        REMOTE_SYNC_CAPTURE_CODE
        .replace("__SAMPLE_HZ__", str(SAMPLE_HZ))
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
        if line.startswith("SYNC_CAPTURE_ERROR"):
            raise RuntimeError(line)
        if line == "BEGIN_IMU_GPS_SYNC_CSV":
            in_csv = True
            print("Capture started.")
            continue
        if line == "END_IMU_GPS_SYNC_CSV":
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
                    print("  progress: %d/%d s" % (elapsed_s, DURATION_S))
                    last_progress = progress
            continue
        print(line)

    raise TimeoutError("Capture timed out before END_IMU_GPS_SYNC_CSV.")


def write_notes(notes_path, timestamp, output_path):
    lines = [
        "Synchronized IMU + GPS capture for 15D ESKF",
        "timestamp: %s" % timestamp,
        "sample_hz: %d" % SAMPLE_HZ,
        "duration_s: %d" % DURATION_S,
        "output_csv: %s" % output_path.name,
        "",
        "Recommended physical experiment:",
        "1. Go outdoors or near a window/open area until GPS has a valid fix.",
        "2. Keep the board still for about 30 seconds at the start.",
        "3. Walk a loop or straight route for 10-15 minutes.",
        "4. Avoid rotating the GPS antenna wildly; keep wiring stable.",
        "5. Keep the board away from keys, motors, speakers, and large metal objects.",
        "6. Keep the board still for about 30 seconds at the end.",
        "",
        "Next analysis script:",
        "firmware/fusion/analyze_eskf_15d_sync.py",
    ]
    notes_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    root = Path(__file__).resolve().parents[2]
    data_dir = root / "data" / "fusion_comparison" / "imu_gps_sync"
    data_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = data_dir / ("imu_gps_sync_%s.csv" % timestamp)
    notes_path = data_dir / ("imu_gps_sync_%s_notes.txt" % timestamp)

    print("Synchronized IMU + GPS capture for 15D ESKF")
    print("Port:", COM_PORT)
    print("Sample rate: %d Hz" % SAMPLE_HZ)
    print("Duration: %d s" % DURATION_S)
    print("Output:", output_path)
    print("")
    print("Do not run this until you are physically ready outdoors.")
    input("Press Enter to start uploading temporary capture code to ESP32...")

    with serial.Serial(COM_PORT, BAUDRATE, timeout=1) as ser:
        start_remote_code(ser, make_remote_code())
        row_count = capture_csv(ser, output_path)
        exit_raw_repl(ser)

    write_notes(notes_path, timestamp, output_path)
    print("")
    print("Capture complete.")
    print("Saved %d lines to: %s" % (row_count, output_path))
    print("Saved notes to:", notes_path)


if __name__ == "__main__":
    main()
