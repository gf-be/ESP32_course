"""
Quick GPS NMEA diagnosis through ESP32 UART2.

This computer-side script runs temporary MicroPython code in ESP32 RAM only.
It does not modify ESP32 flash. After the check, it soft-resets the board so
/main.py starts again.
"""

from datetime import datetime
from pathlib import Path
import serial
import time


COM_PORT = "COM4"
BAUDRATE = 115200
DURATION_S = 25

GPS_UART_ID = 2
GPS_RX_PIN = 16
GPS_TX_PIN = 17
GPS_BAUDRATE = 9600


REMOTE_CODE = r'''
from machine import Pin, UART
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

print("BEGIN_GPS_QUICK_DIAG")
print("# uart,%d,rx,%d,tx,%d,baud,%d,duration,%d" % (
    GPS_UART_ID, GPS_RX_PIN, GPS_TX_PIN, GPS_BAUDRATE, DURATION_S
))

t0 = time.ticks_ms()
count = 0
rmc = 0
gga = 0
gll = 0
fix = 0
last_gga = ""
last_rmc = ""
last_gll = ""
last_status = t0

while time.ticks_diff(time.ticks_ms(), t0) < DURATION_S * 1000:
    raw = uart.readline()
    now = time.ticks_ms()
    if raw:
        try:
            line = raw.decode("ascii").strip()
        except Exception:
            line = ""
        if line.startswith("$"):
            count += 1
            parts = line.split(",")
            typ = parts[0]
            valid = False
            if typ.endswith("RMC"):
                rmc += 1
                last_rmc = line
                valid = len(parts) > 2 and parts[2] == "A"
            elif typ.endswith("GGA"):
                gga += 1
                last_gga = line
                valid = len(parts) > 6 and parts[6] not in ("", "0")
            elif typ.endswith("GLL"):
                gll += 1
                last_gll = line
                valid = len(parts) > 6 and parts[6].startswith("A")
            if valid:
                fix += 1
            if count <= 25 or valid:
                print("%d,%s" % (time.ticks_diff(now, t0), line))
    if time.ticks_diff(now, last_status) >= 5000:
        print("# status_ms,%d,nmea,%d,rmc,%d,gga,%d,gll,%d,fix,%d" % (
            time.ticks_diff(now, t0), count, rmc, gga, gll, fix
        ))
        last_status = now

print("# summary,nmea,%d,rmc,%d,gga,%d,gll,%d,fix,%d" % (count, rmc, gga, gll, fix))
if last_gga:
    print("# last_gga,%s" % last_gga)
if last_rmc:
    print("# last_rmc,%s" % last_rmc)
if last_gll:
    print("# last_gll,%s" % last_gll)
print("END_GPS_QUICK_DIAG")
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
    time.sleep(0.4)
    ser.reset_input_buffer()
    ser.write(b"\x01")
    read_until(ser, b">", timeout=5)


def run_raw_code(ser, code):
    enter_raw_repl(ser)
    data = code.encode("utf-8")
    for i in range(0, len(data), 128):
        ser.write(data[i:i + 128])
        time.sleep(0.005)
    ser.write(b"\x04")
    read_until(ser, b"OK", timeout=5)


def make_remote_code():
    return (
        REMOTE_CODE
        .replace("__GPS_UART_ID__", str(GPS_UART_ID))
        .replace("__GPS_RX_PIN__", str(GPS_RX_PIN))
        .replace("__GPS_TX_PIN__", str(GPS_TX_PIN))
        .replace("__GPS_BAUDRATE__", str(GPS_BAUDRATE))
        .replace("__DURATION_S__", str(DURATION_S))
    )


def soft_reset(ser):
    try:
        ser.write(b"\x02")
        time.sleep(0.2)
        ser.write(b"\x04")
    except Exception:
        pass


def main():
    project_root = Path(__file__).resolve().parents[2]
    out_dir = project_root / "data" / "gps_debug"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / ("gps_quick_diag_%s.txt" % datetime.now().strftime("%Y%m%d_%H%M%S"))

    print("GPS quick diagnose")
    print("Port:", COM_PORT)
    print("Duration:", DURATION_S, "s")
    print("Output:", out_path)

    lines = []
    with serial.Serial(COM_PORT, BAUDRATE, timeout=1) as ser:
        run_raw_code(ser, make_remote_code())
        end_time = time.time() + DURATION_S + 20
        while time.time() < end_time:
            line = ser.readline().decode("utf-8", errors="replace").strip()
            if not line:
                continue
            print(line)
            lines.append(line)
            if line == "END_GPS_QUICK_DIAG":
                break
        out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        soft_reset(ser)

    print("Saved:", out_path)


if __name__ == "__main__":
    main()
