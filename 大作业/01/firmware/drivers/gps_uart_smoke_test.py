"""
GPS UART smoke test for ESP32 MicroPython.

Run this file directly on the ESP32 from Thonny.
It does not save data to flash. It only prints raw NMEA lines and counters.

Expected wiring:
  GPS TX -> ESP32 GPIO16
  GPS RX -> ESP32 GPIO17, optional
  GPS VCC -> module-required supply
  GPS GND -> ESP32 GND
"""

from machine import UART, Pin
import time


GPS_UART_ID = 2
GPS_RX_PIN = 16
GPS_TX_PIN = 17
GPS_BAUDRATE = 9600
DURATION_S = 60
PRINT_RAW_LIMIT = 20


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

print("GPS UART smoke test")
print("UART%d RX=GPIO%d TX=GPIO%d baud=%d" % (GPS_UART_ID, GPS_RX_PIN, GPS_TX_PIN, GPS_BAUDRATE))
print("If nmea_count stays 0, check GPS power, GND, TX->GPIO16, and baudrate.")

t0 = time.ticks_ms()
last_status = t0
nmea_count = 0
fix_count = 0
raw_printed = 0

while time.ticks_diff(time.ticks_ms(), t0) < DURATION_S * 1000:
    raw = uart.readline()
    now = time.ticks_ms()
    if raw:
        try:
            line = raw.decode("ascii").strip()
        except Exception:
            line = ""
        if line.startswith("$"):
            nmea_count += 1
            parts = line.split(",")
            if (parts[0].endswith("RMC") and len(parts) > 2 and parts[2] == "A") or (
                parts[0].endswith("GGA") and len(parts) > 6 and parts[6] not in ("", "0")
            ):
                fix_count += 1
            if raw_printed < PRINT_RAW_LIMIT:
                print("%d,%s" % (time.ticks_diff(now, t0), line))
                raw_printed += 1

    if time.ticks_diff(now, last_status) >= 5000:
        print("# status,%d s,nmea_count,%d,fix_count,%d" % (
            time.ticks_diff(now, t0) // 1000,
            nmea_count,
            fix_count,
        ))
        last_status = now

print("GPS smoke test done. nmea_count=%d, fix_count=%d" % (nmea_count, fix_count))
