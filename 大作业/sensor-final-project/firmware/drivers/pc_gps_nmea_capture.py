"""
Run this file on the computer with Thonny's local Python interpreter.

It captures GPS6MV2 / NEO-6M NMEA sentences through ESP32 UART and saves raw
NMEA data on the computer. The ESP32 only runs temporary MicroPython code in
RAM. Nothing is saved to ESP32 flash.

Before running, check the GPS UART pins below:
  GPS TX -> ESP32 GPS_RX_PIN
  GPS RX -> ESP32 GPS_TX_PIN (optional for receive-only capture)
  GPS VCC -> 3.3V or 5V according to your module board
  GPS GND -> GND
"""

from pathlib import Path
from datetime import datetime
import serial
import time


COM_PORT = "COM7"  # Change this to your ESP32 serial port if needed.
BAUDRATE = 115200

GPS_UART_ID = 2
GPS_RX_PIN = 16  # ESP32 RX pin connected to GPS TX.
GPS_TX_PIN = 17  # ESP32 TX pin connected to GPS RX. Can stay unused.
GPS_BAUDRATE = 9600

DURATION_S = 600  # 10 minutes recommended for an outdoor walking/static track.


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


REMOTE_GPS_CODE = r'''
from machine import UART, Pin
import time

GPS_UART_ID = __GPS_UART_ID__
GPS_RX_PIN = __GPS_RX_PIN__
GPS_TX_PIN = __GPS_TX_PIN__
GPS_BAUDRATE = __GPS_BAUDRATE__
DURATION_S = __DURATION_S__

uart = UART(
    GPS_UART_ID,
    baudrate=GPS_BAUDRATE,
    bits=8,
    parity=None,
    stop=1,
    rx=Pin(GPS_RX_PIN),
    tx=Pin(GPS_TX_PIN),
    timeout=1000,
)

print("BEGIN_GPS_NMEA")
print("# gps_uart_id,%d" % GPS_UART_ID)
print("# gps_rx_pin,%d" % GPS_RX_PIN)
print("# gps_tx_pin,%d" % GPS_TX_PIN)
print("# gps_baudrate,%d" % GPS_BAUDRATE)
print("# duration_s,%d" % DURATION_S)
print("# note,raw NMEA sentences follow")

t0 = time.ticks_ms()
last_status = t0
count = 0
while time.ticks_diff(time.ticks_ms(), t0) < DURATION_S * 1000:
    line = uart.readline()
    now = time.ticks_ms()
    if line:
        try:
            s = line.decode("ascii").strip()
        except Exception:
            s = ""
        if s.startswith("$"):
            print("%d,%s" % (time.ticks_diff(now, t0), s))
            count += 1
    if time.ticks_diff(now, last_status) > 10000:
        print("# status_ms,%d,nmea_count,%d" % (time.ticks_diff(now, t0), count))
        last_status = now

print("END_GPS_NMEA")
'''


def make_remote_code():
    return (
        REMOTE_GPS_CODE
        .replace("__GPS_UART_ID__", str(GPS_UART_ID))
        .replace("__GPS_RX_PIN__", str(GPS_RX_PIN))
        .replace("__GPS_TX_PIN__", str(GPS_TX_PIN))
        .replace("__GPS_BAUDRATE__", str(GPS_BAUDRATE))
        .replace("__DURATION_S__", str(DURATION_S))
    )


def capture_nmea(ser, output_path):
    in_block = False
    rows = []
    last_progress = -1
    end_time = time.time() + DURATION_S + 60

    while time.time() < end_time:
        line = ser.readline().decode("utf-8", errors="replace").strip()
        if not line:
            continue
        print(line)
        if line == "BEGIN_GPS_NMEA":
            in_block = True
            continue
        if line == "END_GPS_NMEA":
            output_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
            return len(rows)
        if in_block:
            rows.append(line)
            if not line.startswith("#"):
                try:
                    elapsed_s = int(line.split(",", 1)[0]) // 1000
                except Exception:
                    continue
                progress = elapsed_s // 30
                if progress != last_progress:
                    print("  progress: %d/%d s" % (elapsed_s, DURATION_S))
                    last_progress = progress

    raise TimeoutError("GPS capture timed out before END_GPS_NMEA.")


def main():
    project_root = Path(__file__).resolve().parents[2]
    data_dir = project_root / "data" / "gps"
    data_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = data_dir / ("gps_nmea_%s.txt" % timestamp)

    print("GPS NMEA capture")
    print("ESP32 port:", COM_PORT)
    print("GPS UART: UART%d RX=GPIO%d TX=GPIO%d baud=%d" % (GPS_UART_ID, GPS_RX_PIN, GPS_TX_PIN, GPS_BAUDRATE))
    print("Duration: %d s" % DURATION_S)
    print("")
    print("Outdoor test suggestion:")
    print("  1. Put the GPS antenna/module outdoors or near a window with open sky.")
    print("  2. Wait 1-3 minutes for satellite lock before pressing Enter.")
    print("  3. For a track map, walk a small loop slowly after lock.")
    print("  4. Keep the antenna side facing upward when possible.")
    print("")
    input("Press Enter to start GPS capture...")

    with serial.Serial(COM_PORT, BAUDRATE, timeout=1) as ser:
        start_remote_code(ser, make_remote_code())
        row_count = capture_nmea(ser, output_path)
        exit_raw_repl(ser)

    print("")
    print("Saved %d lines to: %s" % (row_count, output_path))
    print("Next step: run analyze_gps_track.py to parse CSV and generate folium map.")


if __name__ == "__main__":
    main()
