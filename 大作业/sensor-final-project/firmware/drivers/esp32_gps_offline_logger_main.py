"""
ESP32 GPS offline logger for MicroPython.

Save this file to ESP32 as /main.py when collecting GPS outdoor data.

LED state:
- ESP32 red PWR LED: power indicator, not controlled by firmware.
- GPS module LED: GPS hardware/PPS/fix indicator, not controlled by firmware.
- ESP32 blue/status LED: controlled by GPIO2 in this program.

Blue/status LED pattern:
- Power-on: ON for START_LED_ON_S seconds.
- Ready gap: OFF for START_LED_OFF_S seconds, then GPS capture starts.
- No GPS serial data: OFF.
- Normal NMEA capture: steady 0.5 s ON / 0.5 s OFF blink.
- Valid GPS fix: same regular capture blink; GPS module LED or FIX_LED_PIN can indicate fix.

Optional external LEDs:
- DATA_LED_PIN: short pulse when each NMEA sentence is saved.
- FIX_LED_PIN: ON while a recent valid GPS fix exists.
"""

from machine import UART, Pin
import os
import time


GPS_UART_ID = 2
GPS_RX_PIN = 16       # GPS TX -> ESP32 GPIO16
GPS_TX_PIN = 17       # GPS RX -> ESP32 GPIO17, optional for receive-only use
GPS_BAUDRATE = 9600

STATUS_LED_PIN = 2
DATA_LED_PIN = None   # Set to a GPIO number if you add a separate data LED.
FIX_LED_PIN = None    # Set to a GPIO number if you add a separate fix LED.
LED_ON_VALUE = 1      # Change to 0 if your controllable LED is active-low.

START_LED_ON_S = 3
START_LED_OFF_S = 2
CAPTURE_DURATION_S = 900
LOG_DIR = "/gps_logs"
FLUSH_EVERY_LINES = 20
STATUS_EVERY_S = 10


def ticks_ms():
    return time.ticks_ms()


def ticks_diff(a, b):
    return time.ticks_diff(a, b)


def make_led(pin):
    if pin is None:
        return None
    return Pin(pin, Pin.OUT)


def led_write(led, on):
    if led is not None:
        led.value(LED_ON_VALUE if on else 1 - LED_ON_VALUE)


def led_off_all(status_led, data_led, fix_led):
    led_write(status_led, False)
    led_write(data_led, False)
    led_write(fix_led, False)


def update_status_led(led, mode, now, t0):
    # mode 0: no NMEA, mode 1: NMEA/no fix, mode 2: recent valid fix.
    if mode <= 0:
        # Keep OFF until real GPS serial data is being saved.
        led_write(led, False)
    else:
        # Clear regular blink: GPS serial data is being saved normally.
        led_write(led, ticks_diff(now, t0) % 1000 < 500)


def pulse_data_led(led, now, last_pulse_ms):
    if led is None:
        return last_pulse_ms
    # Limit pulse rate so high-frequency NMEA does not look like always-on.
    if ticks_diff(now, last_pulse_ms) >= 180:
        led_write(led, True)
        return now
    return last_pulse_ms


def update_data_led(led, now, last_pulse_ms):
    if led is not None and ticks_diff(now, last_pulse_ms) >= 70:
        led_write(led, False)


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
    f.write("# start_led_on_s,%d\n" % START_LED_ON_S)
    f.write("# start_led_off_s,%d\n" % START_LED_OFF_S)
    f.write("# capture_duration_s,%d\n" % CAPTURE_DURATION_S)
    f.write("# format,elapsed_ms,nmea_sentence\n")
    f.flush()


def main():
    status_led = make_led(STATUS_LED_PIN)
    data_led = make_led(DATA_LED_PIN)
    fix_led = make_led(FIX_LED_PIN)
    led_off_all(status_led, data_led, fix_led)

    # Clear and visible boot sequence: ON, then OFF, then GPS capture starts.
    led_write(status_led, True)
    time.sleep(START_LED_ON_S)
    led_off_all(status_led, data_led, fix_led)
    time.sleep(START_LED_OFF_S)

    uart = UART(
        GPS_UART_ID,
        baudrate=GPS_BAUDRATE,
        bits=8,
        parity=None,
        stop=1,
        rx=Pin(GPS_RX_PIN),
        tx=Pin(GPS_TX_PIN),
        timeout=100,
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
    print("LED pins: status=%s,data=%s,fix=%s" % (STATUS_LED_PIN, DATA_LED_PIN, FIX_LED_PIN))
    print("LED: no_nmea=off, normal_capture=regular blink, fix=GPS module LED or FIX_LED_PIN")

    t0 = ticks_ms()
    last_status = t0
    last_line_ms = t0
    last_fix_ms = -1000000
    last_data_pulse_ms = -1000000
    nmea_count = 0
    fix_count = 0
    last_gps_utc = ""
    mode = 0

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
                    mode = 1
                    last_data_pulse_ms = pulse_data_led(data_led, now, last_data_pulse_ms)

                    utc = parse_nmea_time(line)
                    if utc:
                        last_gps_utc = utc

                    if has_valid_fix(line):
                        fix_count += 1
                        last_fix_ms = now

                    if nmea_count % FLUSH_EVERY_LINES == 0:
                        f.flush()

            # Pick LED mode from recent data, not just total history.
            if ticks_diff(now, last_line_ms) > 3000:
                mode = 0
            elif ticks_diff(now, last_fix_ms) <= 5000:
                mode = 2
            else:
                mode = 1
            update_status_led(status_led, mode, now, t0)
            update_data_led(data_led, now, last_data_pulse_ms)
            led_write(fix_led, mode == 2)

            if ticks_diff(now, last_status) >= STATUS_EVERY_S * 1000:
                elapsed_s = ticks_diff(now, t0) // 1000
                status = "# status,%d s,nmea,%d,fix,%d,utc,%s,mode,%d" % (
                    elapsed_s,
                    nmea_count,
                    fix_count,
                    last_gps_utc,
                    mode,
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

    # Finished: keep status/fix LEDs ON only when at least one valid fix existed.
    led_write(status_led, fix_count > 0)
    led_write(data_led, False)
    led_write(fix_led, fix_count > 0)


try:
    main()
except Exception as exc:
    print("GPS logger error:", exc)
    try:
        err_led = make_led(STATUS_LED_PIN)
        state = False
        while True:
            state = not state
            led_write(err_led, state)
            time.sleep_ms(120)
    except Exception:
        raise
