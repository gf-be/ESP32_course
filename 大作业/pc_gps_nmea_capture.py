"""
ESP32 GPS offline logger for MicroPython.

Usage:
  1. In Thonny, open this file.
  2. Save it to the ESP32 as /main.py.
  3. Power the ESP32 from a power bank.
  4. The board waits 10 s after boot, then logs GPS NMEA data to /gps_logs/.

The log file name is auto-incremented, so every boot creates a new file and
does not overwrite old data.
"""

from machine import UART, Pin
import os
import time


# ---------------- User settings ----------------
GPS_UART_ID = 2
GPS_RX_PIN = 16       # GPS TX -> ESP32 GPIO16
GPS_TX_PIN = 17       # GPS RX -> ESP32 GPIO17, optional for receive-only use
GPS_BAUDRATE = 9600

LED_PIN = 2           # Common ESP32 blue onboard LED pin
LED_ON_VALUE = 1      # Change to 0 if your board LED is active-low

START_DELAY_S = 10
CAPTURE_DURATION_S = 900   # 15 min. Change to 600 for 10 min, or 1800 for 30 min.
LOG_DIR = "/gps_logs"
FLUSH_EVERY_LINES = 20
STATUS_EVERY_S = 10
# ------------------------------------------------


def ticks_ms():
    return time.ticks_ms()


def ticks_diff(a, b):
    return time.ticks_diff(a, b)


def led_write(led, on):
    led.value(LED_ON_VALUE if on else 1 - LED_ON_VALUE)


def led_blink(led, count=1, on_ms=80, off_ms=120):
    for _ in range(count):
        led_write(led, True)
        time.sleep_ms(on_ms)
        led_write(led, False)
        time.sleep_ms(off_ms)


def ensure_dir(path):
    try:
        os.mkdir(path)
    except OSError:
        pass


def list_dir(path):
    try:
        return os.listdir(path)
    except OSError:
        return []


def next_log_path():
    ensure_dir(LOG_DIR)
    existing = set(list_dir(LOG_DIR))
    index = 1
    while True:
        name = "gps_nmea_%04d.txt" % index
        if name not in existing:
            return LOG_DIR + "/" + name
        index += 1


def parse_nmea_time(line):
    # Returns UTC hhmmss.sss from RMC/GGA if present. This is only for metadata.
    try:
        parts = line.split(",")
        if parts[0].endswith("RMC") or parts[0].endswith("GGA"):
            if len(parts) > 1 and parts[1]:
                return parts[1]
    except Exception:
        pass
    return ""


def has_valid_fix(line):
    try:
        parts = line.split(",")
        sentence = parts[0]
        if sentence.endswith("RMC") and len(parts) > 2:
            return parts[2] == "A"
        if sentence.endswith("GGA") and len(parts) > 6:
            return parts[6] not in ("", "0")
    except Exception:
        pass
    return False


def write_header(f, path):
    f.write("# ESP32 GPS offline logger\n")
    f.write("# log_path,%s\n" % path)
    f.write("# gps_uart_id,%d\n" % GPS_UART_ID)
    f.write("# gps_rx_pin,%d\n" % GPS_RX_PIN)
    f.write("# gps_tx_pin,%d\n" % GPS_TX_PIN)
    f.write("# gps_baudrate,%d\n" % GPS_BAUDRATE)
    f.write("# start_delay_s,%d\n" % START_DELAY_S)
    f.write("# capture_duration_s,%d\n" % CAPTURE_DURATION_S)
    f.write("# format,elapsed_ms,nmea_sentence\n")
    f.flush()


def main():
    led = Pin(LED_PIN, Pin.OUT)
    led_write(led, False)

    # Boot delay: slow blink so you can see the program has started.
    for _ in range(START_DELAY_S):
        led_blink(led, count=1, on_ms=120, off_ms=880)

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

    log_path = next_log_path()
    print("GPS offline logger")
    print("log:", log_path)
    print("duration_s:", CAPTURE_DURATION_S)
    print("GPS UART%d RX=GPIO%d TX=GPIO%d baud=%d" % (
        GPS_UART_ID,
        GPS_RX_PIN,
        GPS_TX_PIN,
        GPS_BAUDRATE,
    ))

    led_blink(led, count=3, on_ms=80, off_ms=80)

    t0 = ticks_ms()
    last_status = t0
    last_line_ms = t0
    first_nmea = False
    first_fix = False
    nmea_count = 0
    fix_count = 0
    last_gps_utc = ""

    with open(log_path, "w") as f:
        write_header(f, log_path)

        while ticks_diff(ticks_ms(), t0) < CAPTURE_DURATION_S * 1000:
            now = ticks_ms()
            raw = uart.readline()

            if raw:
                try:
                    line = raw.decode("ascii").strip()
                except Exception:
                    line = ""

                if line.startswith("$"):
                    elapsed = ticks_diff(now, t0)
                    f.write("%d,%s\n" % (elapsed, line))
                    nmea_count += 1
                    last_line_ms = now

                    utc = parse_nmea_time(line)
                    if utc:
                        last_gps_utc = utc

                    if not first_nmea:
                        first_nmea = True
                        print("GPS data started")
                        led_blink(led, count=5, on_ms=60, off_ms=60)

                    if has_valid_fix(line):
                        fix_count += 1
                        if not first_fix:
                            first_fix = True
                            print("GPS fix valid")
                            led_blink(led, count=8, on_ms=50, off_ms=50)

                    if nmea_count % FLUSH_EVERY_LINES == 0:
                        f.flush()

                    # Visible pulse when normal NMEA output is being saved.
                    led_write(led, True)
                    time.sleep_ms(25)
                    led_write(led, False)

            # If GPS is continuously outputting, keep a short heartbeat.
            if first_nmea and ticks_diff(now, last_line_ms) < 3000:
                if (ticks_diff(now, t0) // 500) % 2 == 0:
                    led_write(led, True)
                else:
                    led_write(led, False)
            else:
                led_write(led, False)

            if ticks_diff(now, last_status) >= STATUS_EVERY_S * 1000:
                elapsed_s = ticks_diff(now, t0) // 1000
                status = "# status,%d s,nmea,%d,fix,%d,utc,%s" % (
                    elapsed_s,
                    nmea_count,
                    fix_count,
                    last_gps_utc,
                )
                print(status)
                f.write(status + "\n")
                f.flush()
                last_status = now

        f.write("# finished,nmea,%d,fix,%d,last_utc,%s\n" % (
            nmea_count,
            fix_count,
            last_gps_utc,
        ))
        f.flush()

    print("GPS logging finished")
    print("saved:", log_path)
    print("nmea_count:", nmea_count)
    print("fix_count:", fix_count)

    # Finished: fast blink, then leave LED on if at least one valid fix existed.
    led_blink(led, count=10, on_ms=60, off_ms=60)
    led_write(led, first_fix)


try:
    main()
except Exception as exc:
    print("GPS logger error:", exc)
    try:
        err_led = Pin(LED_PIN, Pin.OUT)
        while True:
            led_blink(err_led, count=2, on_ms=80, off_ms=160)
            time.sleep_ms(700)
    except Exception:
        raise
