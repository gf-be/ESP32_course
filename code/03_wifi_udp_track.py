"""Step 3 + Step 4 (online): parse GGA/RMC and send JSON over WiFi UDP."""

import json
import socket
import time

import machine
import network

from gnss_nmea import merge_gga_rmc, parse_sentence

try:
    from config_wifi import UDP_IP, UDP_PORT, WIFI_PASS, WIFI_SSID
except ImportError:
    WIFI_SSID = "你的WiFi名称"
    WIFI_PASS = "你的WiFi密码"
    UDP_IP = "192.168.1.100"
    UDP_PORT = 8080


UART_ID = 1
GNSS_RX_PIN = 16
GNSS_TX_PIN = 17
BAUD = 9600
DURATION_S = 20 * 60


def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(False)
    time.sleep(1)
    wlan.active(True)
    if wlan.isconnected():
        return wlan
    print("# wifi connecting to", WIFI_SSID)
    wlan.connect(WIFI_SSID, WIFI_PASS)
    for _ in range(30):
        if wlan.isconnected():
            break
        time.sleep(1)
    if not wlan.isconnected():
        raise OSError("wifi connect failed")
    print("# wifi connected", wlan.ifconfig())
    return wlan


uart = machine.UART(
    UART_ID,
    baudrate=BAUD,
    rx=machine.Pin(GNSS_RX_PIN),
    tx=machine.Pin(GNSS_TX_PIN),
    timeout=1000,
)

wlan = connect_wifi()
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
udp_addr = (UDP_IP, UDP_PORT)

latest_rmc = None
index = 0

print("# step3 wifi udp track")
print("# udp_target,%s:%d" % (UDP_IP, UDP_PORT))
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
        payload = {
            "index": index,
            "elapsed_ms": elapsed_ms,
            "time": merged["time"],
            "date": merged["date"],
            "status": merged["status"],
            "quality": merged["quality"],
            "lat": merged["lat"],
            "lon": merged["lon"],
            "alt": merged["alt"],
            "sats": merged["sats"],
            "hdop": merged["hdop"],
            "speed_knots": merged["speed_knots"],
            "course_deg": merged["course_deg"],
        }
        try:
            sock.sendto(json.dumps(payload).encode("utf-8"), udp_addr)
        except OSError as exc:
            print("# udp_error,%s" % exc)

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
