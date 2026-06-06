"""Real-time GNSS web visualization.

Runs a small Flask page with Leaflet and a WebSocket stream. It can either:

1. Listen for ESP32 UDP JSON packets on port 8080.
2. Replay an existing CSV for demonstration/report screenshots.

Examples:
    python code/realtime_web_visualizer.py --mode replay --csv data/track_flash_outdoor_001.csv
    python code/realtime_web_visualizer.py --mode udp

Open:
    http://127.0.0.1:5000
"""

import argparse
import asyncio
import csv
import json
import socket
import threading
import time
from pathlib import Path

from flask import Flask, Response
import websockets


HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>GNSS Live Track</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <style>
    html, body, #map { height: 100%; margin: 0; }
    .panel {
      position: absolute; z-index: 500; top: 12px; left: 12px;
      background: rgba(255,255,255,.94); border: 1px solid #d0d7de;
      border-radius: 6px; padding: 10px 12px; font: 14px/1.45 system-ui, sans-serif;
      box-shadow: 0 6px 18px rgba(0,0,0,.12); min-width: 260px;
    }
    .value { font-weight: 700; }
  </style>
</head>
<body>
<div id="map"></div>
<div class="panel">
  <div>状态：<span id="status" class="value">连接中</span></div>
  <div>样本：<span id="count" class="value">0</span></div>
  <div>坐标：<span id="coord" class="value">-</span></div>
  <div>质量：Q=<span id="quality" class="value">-</span> sats=<span id="sats" class="value">-</span> HDOP=<span id="hdop" class="value">-</span></div>
</div>
<script>
const map = L.map('map').setView([26.0306, 119.1937], 17);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 20,
  attribution: '&copy; OpenStreetMap'
}).addTo(map);

const track = L.polyline([], {color: '#dc2626', weight: 4, opacity: 0.9}).addTo(map);
let marker = null;
let count = 0;

function colorForHdop(hdop) {
  if (hdop < 1.5) return '#16a34a';
  if (hdop < 3.0) return '#f59e0b';
  return '#dc2626';
}

function update(msg) {
  if (!msg.lat || !msg.lon || Number(msg.quality) <= 0) return;
  const latlng = [Number(msg.lat), Number(msg.lon)];
  count += 1;
  track.addLatLng(latlng);
  if (!marker) {
    marker = L.circleMarker(latlng, {radius: 6, color: '#2563eb', fill: true, fillOpacity: .9}).addTo(map);
    map.setView(latlng, 18);
  } else {
    marker.setLatLng(latlng);
  }
  L.circleMarker(latlng, {
    radius: 3,
    color: colorForHdop(Number(msg.hdop || 99)),
    fill: true,
    fillOpacity: .7
  }).addTo(map);

  document.getElementById('count').textContent = count;
  document.getElementById('coord').textContent = `${Number(msg.lat).toFixed(6)}, ${Number(msg.lon).toFixed(6)}`;
  document.getElementById('quality').textContent = msg.quality ?? '-';
  document.getElementById('sats').textContent = msg.sats ?? '-';
  document.getElementById('hdop').textContent = msg.hdop ?? '-';
}

const ws = new WebSocket(`ws://${location.hostname}:8765`);
ws.onopen = () => document.getElementById('status').textContent = '已连接';
ws.onclose = () => document.getElementById('status').textContent = '已断开';
ws.onerror = () => document.getElementById('status').textContent = '连接错误';
ws.onmessage = (event) => update(JSON.parse(event.data));
</script>
</body>
</html>
"""


clients = set()


async def broadcast(message):
    if not clients:
        return
    text = json.dumps(message)
    disconnected = []
    for client in clients:
        try:
            await client.send(text)
        except Exception:
            disconnected.append(client)
    for client in disconnected:
        clients.discard(client)


async def ws_handler(websocket):
    clients.add(websocket)
    try:
        await websocket.wait_closed()
    finally:
        clients.discard(websocket)


def run_websocket_server():
    async def main():
        async with websockets.serve(ws_handler, "0.0.0.0", 8765):
            await asyncio.Future()

    asyncio.run(main())


def udp_worker(loop):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 8080))
    while True:
        data, _ = sock.recvfrom(2048)
        try:
            msg = json.loads(data.decode("utf-8"))
        except Exception:
            continue
        asyncio.run_coroutine_threadsafe(broadcast(msg), loop)


def replay_worker(loop, csv_path: Path, interval_s: float):
    with csv_path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    while True:
        for row in rows:
            msg = {k: parse_value(v) for k, v in row.items()}
            asyncio.run_coroutine_threadsafe(broadcast(msg), loop)
            time.sleep(interval_s)


def parse_value(value):
    if value is None or value == "":
        return None
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def create_app():
    app = Flask(__name__)

    @app.route("/")
    def index():
        return Response(HTML, mimetype="text/html")

    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["udp", "replay"], default="udp")
    parser.add_argument("--csv", default="data/track_flash_outdoor_001.csv")
    parser.add_argument("--interval", type=float, default=0.25)
    args = parser.parse_args()

    loop = asyncio.new_event_loop()

    def loop_runner():
        asyncio.set_event_loop(loop)
        loop.run_until_complete(websockets.serve(ws_handler, "0.0.0.0", 8765))
        loop.run_forever()

    threading.Thread(target=loop_runner, daemon=True).start()
    time.sleep(0.5)

    if args.mode == "udp":
        threading.Thread(target=udp_worker, args=(loop,), daemon=True).start()
    else:
        threading.Thread(target=replay_worker, args=(loop, Path(args.csv), args.interval), daemon=True).start()

    app = create_app()
    print("Open http://127.0.0.1:5000")
    print("WebSocket ws://127.0.0.1:8765")
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
