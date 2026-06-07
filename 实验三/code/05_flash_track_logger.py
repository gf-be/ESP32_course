"""No-PC outdoor logger: save parsed GNSS track CSV to ESP32 flash.

Upload as main.py when you want the board to start logging automatically from a
power bank. After walking, copy /track_flash.csv back to the PC with mpremote.
"""

import time
import machine
import os

from gnss_nmea import merge_gga_rmc, parse_sentence


UART_ID = 1
GNSS_RX_PIN = 16
GNSS_TX_PIN = 17
BAUD = 9600
DURATION_S = 20 * 60
OUT_PREFIX = "track_flash_"
HEADER = "index,elapsed_ms,time,date,status,quality,lat,lon,alt,sats,hdop,speed_knots,course_deg\n"


def led_write(led, value):
    if led:
        try:
            led.value(value)
        except Exception:
            pass


def led_pulse(led, count, delay_ms=120):
    for _ in range(count):
        led_write(led, 1)
        time.sleep_ms(delay_ms)
        led_write(led, 0)
        time.sleep_ms(delay_ms)


def fmt(value, pattern):
    return "" if value is None else pattern % value


def next_log_name():
    existing = set(os.listdir())
    for number in range(1, 1000):
        name = "%s%03d.csv" % (OUT_PREFIX, number)
        if name not in existing:
            return name
    return "track_flash_overflow.csv"


uart = machine.UART(
    UART_ID,
    baudrate=BAUD,
    rx=machine.Pin(GNSS_RX_PIN),
    tx=machine.Pin(GNSS_TX_PIN),
    timeout=1000,
)

try:
    led = machine.Pin(2, machine.Pin.OUT)
except Exception:
    led = None

latest_rmc = None
index = 0
valid_count = 0
out_file = next_log_name()

print("# flash logger start")
print("# out_file,%s" % out_file)
print("# duration_s,%d" % DURATION_S)
led_pulse(led, 3)

print("# waiting_first_valid_fix")
first_fix = None
while first_fix is None:
    raw = uart.readline()
    if not raw:
        led_pulse(led, 1, 300)
        continue
    try:
        line = raw.decode("ascii", "ignore").strip()
    except Exception:
        continue
    if not line.startswith("$"):
        continue

    msg, data = parse_sentence(line)
    if msg == "RMC" and data:
        latest_rmc = data
    elif msg == "GGA" and data and data.get("valid"):
        first_fix = merge_gga_rmc(data, latest_rmc)
        led_pulse(led, 5, 60)

print("# first_fix,%s,%s" % (first_fix["lat"], first_fix["lon"]))

with open(out_file, "w") as handle:
    handle.write(HEADER)
    start = time.ticks_ms()
    last_flush = start

    while time.ticks_diff(time.ticks_ms(), start) < DURATION_S * 1000:
        raw = uart.readline()
        if not raw:
            led_write(led, 0)
            continue

        try:
            line = raw.decode("ascii", "ignore").strip()
        except Exception:
            continue
        if not line.startswith("$"):
            continue

        msg, data = parse_sentence(line)
        if msg == "RMC" and data:
            latest_rmc = data
            continue
        if msg != "GGA" or not data:
            continue

        merged = merge_gga_rmc(data, latest_rmc)
        if not merged:
            continue

        elapsed_ms = time.ticks_diff(time.ticks_ms(), start)
        row = "%d,%d,%s,%s,%s,%d,%s,%s,%s,%d,%s,%s,%s\n" % (
            index,
            elapsed_ms,
            merged["time"],
            merged["date"],
            merged["status"],
            merged["quality"],
            fmt(merged["lat"], "%.9f"),
            fmt(merged["lon"], "%.9f"),
            fmt(merged["alt"], "%.3f"),
            merged["sats"],
            fmt(merged["hdop"], "%.2f"),
            fmt(merged["speed_knots"], "%.3f"),
            fmt(merged["course_deg"], "%.3f"),
        )
        handle.write(row)

        if merged["quality"] > 0:
            valid_count += 1
            led_pulse(led, 1, 40)

        index += 1
        now = time.ticks_ms()
        if time.ticks_diff(now, last_flush) > 10000:
            handle.flush()
            last_flush = now

    handle.flush()

print("# done,samples,%d,valid,%d" % (index, valid_count))
while True:
    led_pulse(led, 2, 180)
    time.sleep(2)
