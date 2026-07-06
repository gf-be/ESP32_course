"""
PC web display for ESP32 real-time 15D ESKF.

The ESP32 runs esp32_eskf_15d_realtime_main.py and prints ESKF15 CSV records.
This computer-side script reads COM4 directly, saves the records to CSV, and
serves a local browser dashboard.

Open:
  http://127.0.0.1:8767
"""

from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import csv
import json
import math
import serial
import threading
import time
import webbrowser


COM_PORT = "COM4"
BAUDRATE = 115200
WEB_HOST = "127.0.0.1"
WEB_PORT = 8767
HISTORY_MAX = 900
RESET_BOARD_ON_START = True

HEADERS = [
    "t_ms", "initialized", "gps_fix", "satellites", "hdop",
    "gps_lat", "gps_lon", "gps_alt_m",
    "est_lat", "est_lon", "est_alt_m",
    "e_m", "n_m", "u_m",
    "ve_mps", "vn_mps", "vu_mps",
    "roll_deg", "pitch_deg", "yaw_deg",
    "innov_xy_m", "sigma_e_m", "sigma_n_m",
    "imu_hz", "gps_updates", "gps_rejects", "nmea_count",
]

NUMERIC_KEYS = set(HEADERS)
INT_KEYS = {
    "t_ms", "initialized", "gps_fix", "satellites",
    "gps_updates", "gps_rejects", "nmea_count",
}

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FUSION_DIR = Path(__file__).resolve().parent
ECHARTS_JS = FUSION_DIR / "assets" / "echarts.min.js"
PCB_POSE_PHOTO = FUSION_DIR / "assets" / "pcb_pose_photo.png"
OUT_DIR = PROJECT_ROOT / "data" / "fusion_comparison" / "eskf_realtime"
OUT_DIR.mkdir(parents=True, exist_ok=True)
CSV_PATH = OUT_DIR / ("eskf15_web_%s.csv" % datetime.now().strftime("%Y%m%d_%H%M%S"))

STATE_LOCK = threading.Lock()
LATEST = {
    "connected": False,
    "running": True,
    "message": "starting",
    "csv_path": str(CSV_PATH),
    "serial_lines": 0,
    "eskf_rows": 0,
    "last_line": "",
    "last_update_pc": 0.0,
}
HISTORY = deque(maxlen=HISTORY_MAX)


def parse_value(key, value):
    if value == "":
        return None
    try:
        if key in INT_KEYS:
            return int(float(value))
        if key in NUMERIC_KEYS:
            return float(value)
    except Exception:
        return None
    return value


def parse_eskf15(line):
    parts = line.split(",")
    if len(parts) != len(HEADERS) + 1 or parts[0] != "ESKF15":
        return None
    data = {}
    for key, value in zip(HEADERS, parts[1:]):
        data[key] = parse_value(key, value)
    data["pc_time"] = time.time()
    return data


def update_state(**kwargs):
    with STATE_LOCK:
        LATEST.update(kwargs)


def snapshot():
    with STATE_LOCK:
        latest = dict(LATEST)
        history = list(HISTORY)
    latest["history"] = history
    return latest


def soft_reset_board(ser):
    update_state(message="resetting ESP32 main.py")
    ser.write(b"\x03\x03")
    time.sleep(0.3)
    ser.write(b"\x04")
    time.sleep(2.0)
    ser.reset_input_buffer()


def serial_worker():
    update_state(message="opening serial %s" % COM_PORT)
    rows = 0
    serial_lines = 0
    origin_lat = None
    origin_lon = None
    origin_cos = 1.0
    earth_radius = 6378137.0
    try:
        with serial.Serial(COM_PORT, BAUDRATE, timeout=1) as ser, CSV_PATH.open(
            "w", newline="", encoding="utf-8-sig"
        ) as f:
            writer = csv.DictWriter(f, fieldnames=HEADERS)
            writer.writeheader()
            if RESET_BOARD_ON_START:
                soft_reset_board(ser)
            update_state(connected=True, message="serial connected")
            while True:
                raw = ser.readline()
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                serial_lines += 1
                if not line.startswith("ESKF15,"):
                    update_state(
                        serial_lines=serial_lines,
                        last_line=line[-180:],
                        message="waiting for ESKF15 data",
                    )
                    continue

                data = parse_eskf15(line)
                if data is None:
                    update_state(
                        serial_lines=serial_lines,
                        last_line=line[-180:],
                        message="malformed ESKF15 line",
                    )
                    continue

                writer.writerow({key: data.get(key) for key in HEADERS})
                rows += 1
                if rows % 10 == 0:
                    f.flush()

                gps_e = None
                gps_n = None
                gps_lat = data.get("gps_lat")
                gps_lon = data.get("gps_lon")
                if (
                    isinstance(gps_lat, (int, float))
                    and isinstance(gps_lon, (int, float))
                    and abs(gps_lat) > 1e-9
                    and abs(gps_lon) > 1e-9
                ):
                    if origin_lat is None:
                        origin_lat = gps_lat
                        origin_lon = gps_lon
                        origin_cos = math.cos(math.radians(origin_lat))
                    gps_e = math.radians(gps_lon - origin_lon) * earth_radius * origin_cos
                    gps_n = math.radians(gps_lat - origin_lat) * earth_radius

                point = {
                    "t": data.get("t_ms"),
                    "init": data.get("initialized"),
                    "e": data.get("e_m"),
                    "n": data.get("n_m"),
                    "u": data.get("u_m"),
                    "roll": data.get("roll_deg"),
                    "pitch": data.get("pitch_deg"),
                    "yaw": data.get("yaw_deg"),
                    "innov": data.get("innov_xy_m"),
                    "sigma_e": data.get("sigma_e_m"),
                    "sigma_n": data.get("sigma_n_m"),
                    "imu_hz": data.get("imu_hz"),
                    "gps_lat": data.get("gps_lat"),
                    "gps_lon": data.get("gps_lon"),
                    "gps_e": gps_e,
                    "gps_n": gps_n,
                    "est_lat": data.get("est_lat"),
                    "est_lon": data.get("est_lon"),
                }

                with STATE_LOCK:
                    HISTORY.append(point)
                    LATEST.update(data)
                    LATEST.update(
                        connected=True,
                        message="live",
                        serial_lines=serial_lines,
                        eskf_rows=rows,
                        last_line=line[-180:],
                        last_update_pc=time.time(),
                    )
    except Exception as exc:
        update_state(connected=False, running=False, message="serial error: %r" % (exc,))


INDEX_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ESP32 15D ESKF Display</title>
<style>
:root {
  color-scheme: light;
  --bg: #f4f5f2;
  --panel: #ffffff;
  --ink: #17201c;
  --muted: #637066;
  --line: #d9ded7;
  --green: #1d8a5a;
  --orange: #bf6a1d;
  --red: #ba2f3a;
  --blue: #2563eb;
  --teal: #11857c;
  --yellow: #d2a72e;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: Inter, "Segoe UI", "Microsoft YaHei", Arial, sans-serif;
  background: var(--bg);
  color: var(--ink);
}
header {
  height: 58px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 18px;
  border-bottom: 1px solid var(--line);
  background: rgba(255,255,255,0.92);
  position: sticky;
  top: 0;
  z-index: 10;
}
.brand { display: flex; flex-direction: column; gap: 2px; }
.brand strong { font-size: 16px; letter-spacing: 0; }
.brand span { color: var(--muted); font-size: 12px; }
.status { display: flex; align-items: center; gap: 10px; font-size: 13px; color: var(--muted); }
.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  margin: -4px 0 10px;
  color: var(--muted);
  font-size: 12px;
}
.legend span { display: inline-flex; align-items: center; gap: 5px; }
.swatch {
  width: 18px;
  height: 3px;
  border-radius: 999px;
  display: inline-block;
}
.swatch.blue { background: var(--blue); }
.swatch.orange { background: var(--orange); }
.swatch.red { background: var(--red); }
.swatch.teal { background: var(--teal); }
.dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--red);
  box-shadow: 0 0 0 3px rgba(186,47,58,0.12);
}
.dot.live {
  background: var(--green);
  box-shadow: 0 0 0 3px rgba(29,138,90,0.16);
}
main {
  display: grid;
  grid-template-columns: minmax(300px, 0.95fr) minmax(420px, 1.45fr);
  gap: 14px;
  padding: 14px;
}
.panel {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 14px;
  min-width: 0;
}
.panel h2 {
  margin: 0 0 12px;
  font-size: 14px;
  font-weight: 700;
}
.left { display: grid; gap: 14px; align-content: start; }
.stage {
  height: 460px;
  display: grid;
  place-items: center;
  perspective: 900px;
  overflow: hidden;
}
.cube-view {
  transform-style: preserve-3d;
  transform: rotateX(-32deg) rotateY(38deg) rotateZ(-8deg);
}
.board {
  --cuboid-w: 210px;
  --cuboid-h: 280px;
  --cuboid-d: 84px;
  --side-offset: 63px;
  --top-offset: 98px;
  width: var(--cuboid-w);
  height: var(--cuboid-h);
  position: relative;
  transform-style: preserve-3d;
  transition: transform 80ms linear;
  filter: drop-shadow(0 42px 38px rgba(17,31,27,0.34));
}
.cube-face {
  position: absolute;
  left: 0;
  top: 0;
  border: 3px solid rgba(8,32,27,0.86);
  border-radius: 8px;
  display: grid;
  place-items: center;
  overflow: hidden;
  backface-visibility: visible;
  box-shadow: 0 0 0 1px rgba(255,255,255,0.18) inset;
}
.cube-face::before {
  content: "";
  position: absolute;
  inset: 0;
  background:
    linear-gradient(90deg, transparent 0 48%, rgba(255,255,255,0.22) 48% 50%, transparent 50%),
    linear-gradient(0deg, transparent 0 48%, rgba(255,255,255,0.22) 48% 50%, transparent 50%);
  opacity: 0.7;
}
.cube-face::after {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(135deg, rgba(255,255,255,0.24), transparent 34%, rgba(0,0,0,0.20));
  pointer-events: none;
}
.cube-face.front,
.cube-face.back {
  width: var(--cuboid-w);
  height: var(--cuboid-h);
}
.cube-face.right,
.cube-face.left {
  left: var(--side-offset);
  width: var(--cuboid-d);
  height: var(--cuboid-h);
}
.cube-face.top,
.cube-face.bottom {
  top: var(--top-offset);
  width: var(--cuboid-w);
  height: var(--cuboid-d);
}
.cube-face.front {
  background:
    linear-gradient(135deg, rgba(255,255,255,0.05), rgba(0,0,0,0.08)),
    url("/pcb_pose_photo.png") center / cover no-repeat;
  transform: translateZ(42px);
}
.cube-face.back { background: #1b536b; transform: rotateY(180deg) translateZ(42px); }
.cube-face.back {
  background:
    linear-gradient(135deg, rgba(255,255,255,0.05), rgba(0,0,0,0.14)),
    url("/pcb_pose_photo.png") center / cover no-repeat;
  transform: rotateY(180deg) translateZ(42px);
}
.cube-face.right { background: #2f7fbc; transform: rotateY(90deg) translateZ(105px); }
.cube-face.left { background: #7c56ad; transform: rotateY(-90deg) translateZ(105px); }
.cube-face.top { background: #c58632; transform: rotateX(90deg) translateZ(140px); }
.cube-face.bottom { background: #535f6b; transform: rotateX(-90deg) translateZ(140px); }
.face-label {
  position: relative;
  z-index: 2;
  color: rgba(255,255,255,0.86);
  font-size: 18px;
  font-weight: 800;
  letter-spacing: 0;
  text-shadow: 0 2px 5px rgba(0,0,0,0.34);
}
.cube-face.right .face-label,
.cube-face.left .face-label {
  font-size: 13px;
  writing-mode: vertical-rl;
}
.cube-face.top .face-label,
.cube-face.bottom .face-label {
  font-size: 14px;
}
.cube-face.front .face-label {
  display: none;
}
.cube-face.back .face-label {
  display: none;
}
.cube-face.front::before {
  opacity: 0;
}
.cube-face.back::before {
  opacity: 0;
}
.cube-face.front::after {
  background: linear-gradient(135deg, rgba(255,255,255,0.18), transparent 42%, rgba(0,0,0,0.16));
}
.cube-face.back::after {
  background: linear-gradient(135deg, rgba(255,255,255,0.12), transparent 42%, rgba(0,0,0,0.22));
}
.cube-chip {
  position: absolute;
  z-index: 3;
  display: grid;
  place-items: center;
  border-radius: 6px;
  box-shadow: 0 0 0 2px rgba(255,255,255,0.14) inset, 0 8px 14px rgba(0,0,0,0.18);
  color: rgba(255,255,255,0.92);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0;
  text-shadow: 0 1px 2px rgba(0,0,0,0.34);
}
.cube-chip.gps-module { width: 80px; height: 46px; left: 24px; top: 18px; background: #1d6fa6; }
.cube-chip.esp32-module { width: 76px; height: 126px; right: 12px; top: 17px; background: #26333b; }
.cube-chip.mpu { width: 52px; height: 45px; left: 126px; top: 86px; background: #245fa8; }
.cube-chip.bmp { width: 34px; height: 34px; left: 80px; bottom: 18px; background: #62459b; }
.cube-chip.hmc { width: 48px; height: 34px; left: 24px; top: 82px; background: #2b7bb5; }
.cube-chip.led-dot {
  width: 12px;
  height: 12px;
  left: 16px;
  bottom: 12px;
  border-radius: 999px;
  background: #9aff30;
  box-shadow: 0 0 0 2px rgba(255,255,255,0.24) inset, 0 0 12px rgba(154,255,48,0.95);
}
.cube-face.front .cube-chip {
  display: none;
}
.axis {
  position: absolute;
  z-index: 4;
  display: none;
  font-size: 13px;
  font-weight: 700;
  color: white;
  text-shadow: 0 1px 2px rgba(0,0,0,0.35);
  background: rgba(8,22,18,0.44);
  border: 1px solid rgba(255,255,255,0.26);
  border-radius: 999px;
  padding: 3px 7px;
}
.axis.x { right: -58px; top: 58px; }
.axis.y { left: 100px; top: -54px; }
.axis.z { left: 8px; bottom: -52px; }
.axis-triad {
  position: absolute;
  left: 50%;
  top: 50%;
  width: 0;
  height: 0;
  z-index: 30;
  transform-style: preserve-3d;
  transform: translateZ(72px);
  pointer-events: none;
}
.axis-origin {
  position: absolute;
  left: 0;
  top: 0;
  width: 16px;
  height: 16px;
  border-radius: 999px;
  background: #ffffff;
  transform: translate(-50%, -50%);
  box-shadow: 0 0 0 3px rgba(12,24,20,0.65), 0 5px 12px rgba(0,0,0,0.34);
}
.axis-line {
  position: absolute;
  left: 0;
  top: 0;
  width: 118px;
  height: 0;
  transform-style: preserve-3d;
  transform-origin: 0 0;
}
.axis-line i {
  position: absolute;
  left: 0;
  top: -4px;
  width: 100%;
  height: 8px;
  border-radius: 999px;
  box-shadow: 0 3px 10px rgba(0,0,0,0.30);
}
.axis-line i::after {
  content: "";
  position: absolute;
  right: -13px;
  top: -6px;
  width: 0;
  height: 0;
  border-top: 10px solid transparent;
  border-bottom: 10px solid transparent;
}
.axis-line b {
  position: absolute;
  left: 126px;
  top: -18px;
  min-width: 34px;
  padding: 4px 7px;
  border-radius: 999px;
  color: #fff;
  font-size: 15px;
  font-weight: 900;
  letter-spacing: 0;
  text-align: center;
  text-shadow: 0 1px 2px rgba(0,0,0,0.45);
  box-shadow: 0 4px 12px rgba(0,0,0,0.22);
}
.axis-line.x-body { transform: rotateZ(0deg); }
.axis-line.y-body { transform: rotateZ(-90deg); }
.axis-line.z-body { transform: rotateY(-64deg) rotateZ(34deg); }
.axis-line.x-body i,
.axis-line.x-body b { background: #e53935; }
.axis-line.x-body i::after { border-left: 16px solid #e53935; }
.axis-line.y-body i,
.axis-line.y-body b { background: #20a857; }
.axis-line.y-body i::after { border-left: 16px solid #20a857; }
.axis-line.z-body i,
.axis-line.z-body b { background: #2563eb; }
.axis-line.z-body i::after { border-left: 16px solid #2563eb; }
.pose-actions {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
  gap: 8px;
  margin: 2px 0 10px;
}
.pose-actions button {
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #f7faf8;
  color: var(--ink);
  height: 32px;
  padding: 0 12px;
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}
.pose-actions button:hover { border-color: #9fb5a8; background: #eef5f0; }
.pose-actions span { color: var(--muted); font-size: 12px; }
.cards {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}
.metric {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 10px;
  min-height: 68px;
  background: #fbfcfa;
}
.metric label {
  display: block;
  color: var(--muted);
  font-size: 12px;
  margin-bottom: 6px;
}
.metric b {
  font-size: 22px;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0;
}
.metric small { color: var(--muted); margin-left: 3px; }
.wide { grid-column: 1 / -1; }
.grid2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}
.chart {
  width: 100%;
  height: 260px;
  display: block;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
}
.log {
  color: var(--muted);
  font-size: 12px;
  font-family: Consolas, "Courier New", monospace;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
@media (max-width: 900px) {
  main { grid-template-columns: 1fr; }
  .cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .grid2 { grid-template-columns: 1fr; }
}
</style>
</head>
<body>
<header>
  <div class="brand">
    <strong>ESP32 15D ESKF 实时融合看板</strong>
    <span id="csv">CSV</span>
  </div>
  <div class="status"><span id="dot" class="dot"></span><span id="status">connecting</span></div>
</header>
<main>
  <section class="left">
    <div class="panel">
      <h2>姿态显示</h2>
      <div class="stage">
        <div class="cube-view">
          <div id="board" class="board">
            <div class="cube-face front">
              <span class="face-label">PCB TOP</span>
              <span class="cube-chip gps-module">GPS</span>
              <span class="cube-chip esp32-module">ESP32</span>
              <span class="cube-chip mpu">MPU</span>
              <span class="cube-chip bmp">BMP</span>
              <span class="cube-chip hmc">HMC</span>
              <span class="cube-chip led-dot"></span>
            </div>
            <div class="cube-face back"><span class="face-label">PCB BOTTOM</span></div>
            <div class="cube-face right"><span class="face-label">ESP32 SIDE</span></div>
            <div class="cube-face left"><span class="face-label">SENSOR SIDE</span></div>
            <div class="cube-face top"><span class="face-label">GPS SIDE</span></div>
            <div class="cube-face bottom"><span class="face-label">LED SIDE</span></div>
            <div class="axis-triad">
              <span class="axis-line x-body"><i></i><b>+X</b></span>
              <span class="axis-line y-body"><i></i><b>+Y</b></span>
              <span class="axis-line z-body"><i></i><b>+Z</b></span>
              <span class="axis-origin"></span>
            </div>
            <span class="axis x">+X</span>
            <span class="axis y">+Y</span>
            <span class="axis z">+Z</span>
          </div>
        </div>
      </div>
      <div class="pose-actions">
        <button id="zeroPose" type="button">设当前为显示零位</button>
        <button id="resetPose" type="button">恢复原始姿态</button>
        <span id="zeroState">显示原始姿态</span>
      </div>
      <div class="cards">
        <div class="metric"><label>横滚 Roll</label><b id="roll">0.00</b><small>deg</small></div>
        <div class="metric"><label>俯仰 Pitch</label><b id="pitch">0.00</b><small>deg</small></div>
        <div class="metric"><label>航向 Yaw</label><b id="yaw">0.00</b><small>deg</small></div>
      </div>
    </div>
    <div class="panel">
      <h2>定位与运行状态</h2>
      <div class="cards">
        <div class="metric"><label>GPS 定位</label><b id="gps">等待</b></div>
        <div class="metric"><label>卫星数</label><b id="sat">0</b><small>颗</small></div>
        <div class="metric"><label>HDOP</label><b id="hdop">0.00</b></div>
        <div class="metric"><label>板上更新率</label><b id="hz">0.0</b><small>Hz</small></div>
        <div class="metric"><label>GPS 融合次数</label><b id="upd">0</b></div>
        <div class="metric"><label>异常拒绝次数</label><b id="rej">0</b></div>
      </div>
    </div>
  </section>
  <section class="panel">
    <h2>融合位置 ENU</h2>
    <div class="cards">
      <div class="metric"><label>东向 East</label><b id="east">0.00</b><small>m</small></div>
      <div class="metric"><label>北向 North</label><b id="north">0.00</b><small>m</small></div>
      <div class="metric"><label>高度 Up</label><b id="up">0.00</b><small>m</small></div>
      <div class="metric"><label>水平速度</label><b id="speed">0.00</b><small>m/s</small></div>
      <div class="metric"><label>GPS-ESKF 差值</label><b id="innov">0.00</b><small>m</small></div>
      <div class="metric"><label>位置不确定度</label><b id="sigma">0.00</b><small>m</small></div>
    </div>
    <div style="height:14px"></div>
    <div class="grid2">
      <div>
        <h2>轨迹对比</h2>
        <div class="legend">
          <span><i class="swatch orange"></i>原始 GPS</span>
          <span><i class="swatch blue"></i>ESKF 融合</span>
          <span><i class="swatch red"></i>当前位置</span>
        </div>
        <div id="track" class="chart"></div>
      </div>
      <div>
        <h2>姿态角曲线</h2>
        <div class="legend">
          <span><i class="swatch blue"></i>Roll</span>
          <span><i class="swatch teal"></i>Pitch</span>
          <span><i class="swatch orange"></i>Yaw</span>
        </div>
        <div id="rpy" class="chart"></div>
      </div>
    </div>
    <div style="height:14px"></div>
    <div>
      <h2>滤波一致性</h2>
      <div class="legend">
        <span><i class="swatch red"></i>GPS-ESKF 差值</span>
        <span><i class="swatch blue"></i>东向不确定度</span>
        <span><i class="swatch teal"></i>北向不确定度</span>
      </div>
      <div id="quality" class="chart"></div>
    </div>
    <div style="height:12px"></div>
    <div id="line" class="log">waiting</div>
  </section>
</main>
<script src="/echarts.min.js"></script>
<script>
const els = {};
for (const id of ["dot","status","csv","board","zeroPose","resetPose","zeroState","roll","pitch","yaw","gps","sat","hdop","hz","upd","rej","east","north","up","speed","innov","sigma","line"]) {
  els[id] = document.getElementById(id);
}
let latest = null;
let poseZero = null;
const DISPLAY_ROTATION = {
  rollToY: -1,
  pitchToX: 1,
  yawToZ: 1,
};
function num(v, digits=2) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "--";
  return Number(v).toFixed(digits);
}
function setMetric(id, value, digits=2) { els[id].textContent = num(value, digits); }
function angleDiff(current, zero) {
  let d = Number(current || 0) - Number(zero || 0);
  while (d > 180) d -= 360;
  while (d < -180) d += 360;
  return d;
}
function poseForDisplay(r, p, y) {
  if (!poseZero) return {r, p, y};
  return {
    r: angleDiff(r, poseZero.r),
    p: angleDiff(p, poseZero.p),
    y: angleDiff(y, poseZero.y),
  };
}
function boardRotationForDisplay(pose) {
  return {
    x: DISPLAY_ROTATION.pitchToX * pose.p,
    y: DISPLAY_ROTATION.rollToY * pose.r,
    z: DISPLAY_ROTATION.yawToZ * pose.y,
  };
}
const charts = {};
const chartColors = {
  blue: "#2563eb",
  teal: "#11857c",
  orange: "#bf6a1d",
  red: "#ba2f3a",
  muted: "#637066",
  grid: "#e5e9e1"
};
function getChart(id) {
  const el = document.getElementById(id);
  if (!window.echarts) {
    el.textContent = "ECharts 加载失败，请联网或放置本地 echarts.min.js";
    el.style.display = "grid";
    el.style.placeItems = "center";
    el.style.color = chartColors.muted;
    return null;
  }
  if (!charts[id]) charts[id] = echarts.init(el, null, {renderer: "canvas"});
  return charts[id];
}
function validNum(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}
function elapsedSec(hist, p) {
  const t0 = hist.length ? Number(hist[0].t || 0) : 0;
  return ((Number(p.t || 0) - t0) / 1000).toFixed(2);
}
function xySeries(hist, xKey, yKey) {
  const out = [];
  for (const p of hist) {
    const x = validNum(p[xKey]), y = validNum(p[yKey]);
    if (x !== null && y !== null) out.push([x, y]);
  }
  return out;
}
function timeSeries(hist, key) {
  const out = [];
  for (const p of hist) {
    const y = validNum(p[key]);
    if (y !== null) out.push([Number(elapsedSec(hist, p)), y]);
  }
  return out;
}
function baseOption() {
  return {
    animation: false,
    backgroundColor: "#fff",
    textStyle: {fontFamily: 'Inter, "Segoe UI", "Microsoft YaHei", Arial, sans-serif', color: "#17201c"},
    tooltip: {trigger: "axis", confine: true, backgroundColor: "rgba(255,255,255,0.96)", borderColor: "#d9ded7"},
    legend: {top: 8, left: 10, itemWidth: 18, itemHeight: 8, textStyle: {color: chartColors.muted}},
    grid: {left: 54, right: 20, top: 46, bottom: 44},
    dataZoom: [{type: "inside", throttle: 80}],
  };
}
function drawTrack(hist) {
  const chart = getChart("track");
  if (!chart) return;
  const gps = xySeries(hist, "gps_e", "gps_n");
  const eskf = xySeries(hist, "e", "n");
  const last = eskf.length ? [eskf[eskf.length - 1]] : [];
  chart.setOption({
    ...baseOption(),
    tooltip: {trigger: "item", confine: true, formatter: p => `${p.seriesName}<br>East: ${num(p.value[0])} m<br>North: ${num(p.value[1])} m`},
    xAxis: {type: "value", name: "East (m)", scale: true, splitLine: {lineStyle: {color: chartColors.grid}}},
    yAxis: {type: "value", name: "North (m)", scale: true, splitLine: {lineStyle: {color: chartColors.grid}}},
    series: [
      {name: "原始 GPS", type: "line", data: gps, showSymbol: false, smooth: true, lineStyle: {width: 2, color: chartColors.orange, type: "dashed"}},
      {name: "ESKF 融合", type: "line", data: eskf, showSymbol: false, smooth: true, lineStyle: {width: 3, color: chartColors.blue}},
      {name: "当前位置", type: "scatter", data: last, symbolSize: 12, itemStyle: {color: chartColors.red}},
    ],
  }, false);
}
function drawRpy(hist) {
  const chart = getChart("rpy");
  if (!chart) return;
  chart.setOption({
    ...baseOption(),
    xAxis: {type: "value", name: "Time (s)", splitLine: {lineStyle: {color: chartColors.grid}}},
    yAxis: {type: "value", name: "Angle (deg)", scale: true, splitLine: {lineStyle: {color: chartColors.grid}}},
    series: [
      {name: "Roll 横滚", type: "line", data: timeSeries(hist, "roll"), showSymbol: false, smooth: true, lineStyle: {width: 2.4, color: chartColors.blue}},
      {name: "Pitch 俯仰", type: "line", data: timeSeries(hist, "pitch"), showSymbol: false, smooth: true, lineStyle: {width: 2.4, color: chartColors.teal}},
      {name: "Yaw 航向", type: "line", data: timeSeries(hist, "yaw"), showSymbol: false, smooth: true, lineStyle: {width: 2.4, color: chartColors.orange}},
    ],
  }, false);
}
function drawQuality(hist) {
  const chart = getChart("quality");
  if (!chart) return;
  chart.setOption({
    ...baseOption(),
    xAxis: {type: "value", name: "Time (s)", splitLine: {lineStyle: {color: chartColors.grid}}},
    yAxis: {type: "value", name: "Meter (m)", min: 0, scale: true, splitLine: {lineStyle: {color: chartColors.grid}}},
    series: [
      {name: "GPS-ESKF 差值", type: "line", data: timeSeries(hist, "innov"), showSymbol: false, smooth: true, lineStyle: {width: 2.6, color: chartColors.red}},
      {name: "东向不确定度", type: "line", data: timeSeries(hist, "sigma_e"), showSymbol: false, smooth: true, lineStyle: {width: 2.2, color: chartColors.blue}},
      {name: "北向不确定度", type: "line", data: timeSeries(hist, "sigma_n"), showSymbol: false, smooth: true, lineStyle: {width: 2.2, color: chartColors.teal}},
    ],
  }, false);
}
function applyData(data) {
  latest = data;
  const isLive = data.connected && (Date.now()/1000 - (data.last_update_pc || 0) < 3.0);
  els.dot.classList.toggle("live", isLive);
  els.status.textContent = `${data.message || "waiting"} · saved rows ${data.eskf_rows || 0}`;
  els.csv.textContent = data.csv_path || "CSV";
  const r = Number(data.roll_deg || 0), p = Number(data.pitch_deg || 0), y = Number(data.yaw_deg || 0);
  const pose = poseForDisplay(r, p, y);
  const rot = boardRotationForDisplay(pose);
  els.board.style.transform = `rotateZ(${rot.z}deg) rotateX(${rot.x}deg) rotateY(${rot.y}deg)`;
  if (els.zeroState) els.zeroState.textContent = poseZero ? "已使用当前姿态作为显示零位" : "显示原始姿态";
  setMetric("roll", data.roll_deg); setMetric("pitch", data.pitch_deg); setMetric("yaw", data.yaw_deg);
  els.gps.textContent = Number(data.gps_fix || 0) > 0 ? "已定位" : "等待";
  els.sat.textContent = data.satellites ?? 0;
  setMetric("hdop", data.hdop); setMetric("hz", data.imu_hz, 1);
  els.upd.textContent = data.gps_updates ?? 0;
  els.rej.textContent = data.gps_rejects ?? 0;
  const ve = Number(data.ve_mps || 0), vn = Number(data.vn_mps || 0);
  setMetric("speed", Math.sqrt(ve * ve + vn * vn));
  setMetric("east", data.e_m); setMetric("north", data.n_m); setMetric("up", data.u_m);
  setMetric("innov", data.innov_xy_m);
  const se = Number(data.sigma_e_m || 0), sn = Number(data.sigma_n_m || 0);
  setMetric("sigma", Math.sqrt(se * se + sn * sn));
  els.line.textContent = data.last_line || "";
  const hist = data.history || [];
  drawTrack(hist); drawRpy(hist); drawQuality(hist);
}
const es = new EventSource("/events");
es.onmessage = ev => applyData(JSON.parse(ev.data));
es.onerror = () => { els.status.textContent = "browser waiting for server"; els.dot.classList.remove("live"); };
if (els.zeroPose) {
  els.zeroPose.onclick = () => {
    if (!latest) return;
    poseZero = {
      r: Number(latest.roll_deg || 0),
      p: Number(latest.pitch_deg || 0),
      y: Number(latest.yaw_deg || 0),
    };
    applyData(latest);
  };
}
if (els.resetPose) {
  els.resetPose.onclick = () => {
    poseZero = null;
    if (latest) applyData(latest);
  };
}
window.addEventListener("resize", () => {
  for (const c of Object.values(charts)) c.resize();
  if (latest) applyData(latest);
});
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def send_text(self, status, content, content_type="text/plain; charset=utf-8"):
        body = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_bytes(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            self.send_text(200, INDEX_HTML, "text/html; charset=utf-8")
            return
        if self.path.startswith("/echarts.min.js"):
            if ECHARTS_JS.exists():
                self.send_bytes(200, ECHARTS_JS.read_bytes(), "application/javascript; charset=utf-8")
            else:
                self.send_text(404, "echarts.min.js not found")
            return
        if self.path.startswith("/pcb_pose_photo.png"):
            if PCB_POSE_PHOTO.exists():
                self.send_bytes(200, PCB_POSE_PHOTO.read_bytes(), "image/png")
            else:
                self.send_text(404, "pcb_pose_photo.png not found")
            return
        if self.path.startswith("/api/state"):
            self.send_text(200, json.dumps(snapshot(), ensure_ascii=False), "application/json; charset=utf-8")
            return
        if self.path.startswith("/events"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            while True:
                try:
                    payload = json.dumps(snapshot(), ensure_ascii=False)
                    self.wfile.write(("data: %s\n\n" % payload).encode("utf-8"))
                    self.wfile.flush()
                    time.sleep(0.2)
                except Exception:
                    break
            return
        self.send_text(404, "not found")


def main():
    print("ESP32 real-time 15D ESKF web display")
    print("Serial:", COM_PORT, BAUDRATE)
    print("CSV:", CSV_PATH)
    print("ECharts:", ECHARTS_JS)
    print("Web: http://%s:%d" % (WEB_HOST, WEB_PORT))

    th = threading.Thread(target=serial_worker, daemon=True)
    th.start()

    server = ThreadingHTTPServer((WEB_HOST, WEB_PORT), Handler)
    webbrowser.open("http://%s:%d" % (WEB_HOST, WEB_PORT))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
