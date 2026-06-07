"""Step 4 fallback: outdoor walk logging over USB serial (no WiFi required)."""

import time
import machine

from gnss_nmea import merge_gga_rmc, parse_sentence


UART_ID = 1
GNSS_RX_PIN = 16
GNSS_TX_PIN = 17
BAUD = 9600
DURATION_S = 20 * 60


uart = machine.UART(
    UART_ID,
    baudrate=BAUD,
    rx=machine.Pin(GNSS_RX_PIN),
    tx=machine.Pin(GNSS_TX_PIN),
    timeout=1000,
)

latest_rmc = None
index = 0

print("# step4 serial outdoor track logger")
print("# duration_s,%d" % DURATION_S)
print("index,elapsed_ms,time,date,status,quality,lat,lon,alt,sats,hdop,speed_knots,course_deg")

start = time.ticks_ms()
while time.ticks_diff(time.ticks_ms(), start) < DURATION_S * 1000:
    raw = uart.readline()
    if not raw:
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
    elif msg == "GGA" and data:
        merged = merge_gga_rmc(data, latest_rmc)
        if not merged:
            continue

        elapsed_ms = time.ticks_diff(time.ticks_ms(), start)
        lat = "" if merged["lat"] is None else "%.9f" % merged["lat"]
        lon = "" if merged["lon"] is None else "%.9f" % merged["lon"]
        alt = "" if merged["alt"] is None else "%.3f" % merged["alt"]
        hdop = "" if merged["hdop"] is None else "%.2f" % merged["hdop"]
        speed = "" if merged["speed_knots"] is None else "%.3f" % merged["speed_knots"]
        course = "" if merged["course_deg"] is None else "%.3f" % merged["course_deg"]
        print(
            "%d,%d,%s,%s,%s,%d,%s,%s,%s,%d,%s,%s,%s"
            % (
                index,
                elapsed_ms,
                merged["time"],
                merged["date"],
                merged["status"],
                merged["quality"],
                lat,
                lon,
                alt,
                merged["sats"],
                hdop,
                speed,
                course,
            )
        )
        index += 1

print("# done,samples,%d" % index)
