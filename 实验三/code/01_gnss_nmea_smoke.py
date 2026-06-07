"""Step 1: verify wiring and print raw/parsed NMEA for 30 seconds."""

import time
import machine

from gnss_nmea import parse_sentence


UART_ID = 1
GNSS_RX_PIN = 16
GNSS_TX_PIN = 17
BAUD = 9600
TEST_SECONDS = 30


uart = machine.UART(
    UART_ID,
    baudrate=BAUD,
    rx=machine.Pin(GNSS_RX_PIN),
    tx=machine.Pin(GNSS_TX_PIN),
    timeout=1000,
)

print("# step1 gnss smoke test")
print("# uart_id,%d" % UART_ID)
print("# rx_gpio,%d" % GNSS_RX_PIN)
print("# tx_gpio,%d" % GNSS_TX_PIN)
print("# baud,%d" % BAUD)
print("# waiting for NMEA lines")

start = time.ticks_ms()
gga_count = 0
rmc_count = 0
valid_fix_count = 0

while time.ticks_diff(time.ticks_ms(), start) < TEST_SECONDS * 1000:
    raw = uart.readline()
    if not raw:
        continue
    try:
        line = raw.decode("ascii", "ignore").strip()
    except Exception:
        continue
    if not line.startswith("$"):
        continue

    print(line)
    msg, data = parse_sentence(line)
    if msg == "GGA" and data:
        gga_count += 1
        if data["valid"]:
            valid_fix_count += 1
        print(
            "# GGA fix=%d sat=%d hdop=%s lat=%s lon=%s alt=%s"
            % (
                data["quality"],
                data["num_sat"],
                data["hdop"],
                data["lat_deg"],
                data["lon_deg"],
                data["alt_m"],
            )
        )
    elif msg == "RMC" and data:
        rmc_count += 1
        print("# RMC status=%s date=%s speed_knots=%s course=%s" % (
            data["status"],
            data["utc_date"],
            data["speed_knots"],
            data["course_deg"],
        ))

print("# gga_count,%d" % gga_count)
print("# rmc_count,%d" % rmc_count)
print("# valid_fix_count,%d" % valid_fix_count)
