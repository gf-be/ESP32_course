"""
Run this file on the computer with Thonny's local Python interpreter.

It starts a local web page for real-time 3D attitude display. The script sends
temporary MicroPython code to ESP32 RAM, reads roll/pitch/yaw from the serial
port, and serves a browser-based 3D board.

Nothing is saved to ESP32 flash.

Open after running:
  http://127.0.0.1:8765
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
import json
import math
import serial
import threading
import time


COM_PORT = "COM7"
BAUDRATE = 115200
WEB_HOST = "127.0.0.1"
WEB_PORT = 8765


LATEST = {
    "connected": False,
    "t_ms": 0,
    "roll": 0.0,
    "pitch": 0.0,
    "yaw": 0.0,
    "temp": 0.0,
    "update_hz": 0.0,
    "serial_lines": 0,
    "message": "waiting",
}


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
    time.sleep(0.2)
    ser.reset_input_buffer()
    ser.write(b"\x01")
    read_until(ser, b">", timeout=5)


def exit_raw_repl(ser):
    ser.write(b"\x02")
    time.sleep(0.2)


def start_remote_code(ser, code):
    enter_raw_repl(ser)
    data = code.encode("utf-8")
    for i in range(0, len(data), 128):
        ser.write(data[i:i + 128])
        time.sleep(0.01)
    ser.write(b"\x04")
    read_until(ser, b"OK", timeout=5)


REMOTE_ATTITUDE_CODE = r'''
from machine import Pin, I2C
import time
import struct
import math

SDA_PIN = 21
SCL_PIN = 22
I2C_FREQ = 400000
MPU_ADDR = 0x68
MAG_ADDR = 0x1E
TARGET_HZ = 50
ALPHA = 0.98

GYRO_BIAS_X = 0.228303741
GYRO_BIAS_Y = 0.964654373
GYRO_BIAS_Z = -0.100939275

def init_imu(i2c):
    i2c.writeto_mem(MPU_ADDR, 0x6B, b"\x00")
    time.sleep_ms(100)
    i2c.writeto_mem(MPU_ADDR, 0x1A, b"\x03")
    i2c.writeto_mem(MPU_ADDR, 0x1B, b"\x00")
    i2c.writeto_mem(MPU_ADDR, 0x1C, b"\x00")
    time.sleep_ms(100)

def init_mag(i2c):
    i2c.writeto_mem(MAG_ADDR, 0x00, b"\x70")
    i2c.writeto_mem(MAG_ADDR, 0x01, b"\x20")
    i2c.writeto_mem(MAG_ADDR, 0x02, b"\x00")
    time.sleep_ms(100)

def read_imu(i2c):
    raw = i2c.readfrom_mem(MPU_ADDR, 0x3B, 14)
    ax, ay, az, temp, gx, gy, gz = struct.unpack(">hhhhhhh", raw)
    return (
        ax / 16384.0,
        ay / 16384.0,
        az / 16384.0,
        temp / 340.0 + 36.53,
        gx / 131.0 - GYRO_BIAS_X,
        gy / 131.0 - GYRO_BIAS_Y,
        gz / 131.0 - GYRO_BIAS_Z,
    )

def read_mag(i2c):
    raw = i2c.readfrom_mem(MAG_ADDR, 0x03, 6)
    x, z, y = struct.unpack(">hhh", raw)
    return x - 77.082135, y + 94.427834, z + 36.852085

def wrap_deg(x):
    while x > 180:
        x -= 360
    while x < -180:
        x += 360
    return x

def accel_angles(ax, ay, az):
    roll = math.atan2(ay, az) * 57.2957795
    pitch = math.atan2(-ax, math.sqrt(ay * ay + az * az)) * 57.2957795
    return roll, pitch

def mag_yaw(mx, my, mz, roll_deg, pitch_deg):
    roll = roll_deg / 57.2957795
    pitch = pitch_deg / 57.2957795
    mx2 = mx * math.cos(pitch) + mz * math.sin(pitch)
    my2 = mx * math.sin(roll) * math.sin(pitch) + my * math.cos(roll) - mz * math.sin(roll) * math.cos(pitch)
    return math.atan2(-my2, mx2) * 57.2957795

i2c = I2C(0, sda=Pin(SDA_PIN), scl=Pin(SCL_PIN), freq=I2C_FREQ)
scan = i2c.scan()
if MPU_ADDR not in scan:
    print("ATT_WEB_ERROR,no_0x68,scan=" + ",".join(hex(x) for x in scan))
else:
    init_imu(i2c)
    has_mag = MAG_ADDR in scan
    if has_mag:
        init_mag(i2c)
    print("ATT_WEB_BEGIN")
    print("t_ms,roll_deg,pitch_deg,yaw_deg,temp_c,update_hz")

    roll = 0.0
    pitch = 0.0
    yaw = 0.0
    interval_ms = int(1000 / TARGET_HZ)
    last = time.ticks_ms()
    next_t = last
    fps_t0 = last
    count = 0

    while True:
        now = time.ticks_ms()
        dt = max(0.001, time.ticks_diff(now, last) / 1000.0)
        last = now
        ax, ay, az, temp, gx, gy, gz = read_imu(i2c)
        ar, ap = accel_angles(ax, ay, az)
        if has_mag:
            mx, my, mz = read_mag(i2c)
            myaw = mag_yaw(mx, my, mz, ar, ap)
        else:
            myaw = yaw
        roll = ALPHA * (roll + gx * dt) + (1.0 - ALPHA) * ar
        pitch = ALPHA * (pitch + gy * dt) + (1.0 - ALPHA) * ap
        yaw_pred = yaw + gz * dt
        yaw = wrap_deg(yaw_pred + (1.0 - ALPHA) * wrap_deg(myaw - yaw_pred))
        count += 1
        elapsed = time.ticks_diff(now, fps_t0)
        update_hz = 0.0
        if elapsed >= 1000:
            update_hz = count * 1000.0 / elapsed
            count = 0
            fps_t0 = now
        print("%d,%.3f,%.3f,%.3f,%.3f,%.2f" % (now, roll, pitch, yaw, temp, update_hz))
        next_t = time.ticks_add(next_t, interval_ms)
        wait_ms = time.ticks_diff(next_t, time.ticks_ms())
        if wait_ms > 0:
            time.sleep_ms(wait_ms)
'''


HTML = r'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ESP32 Attitude Board</title>
<style>
  :root { --bg: #111827; --panel: #1f2937; --text: #e5e7eb; --muted: #9ca3af; --accent: #38bdf8; }
  body { margin: 0; min-height: 100vh; background: radial-gradient(circle at 20% 10%, #1e3a5f, var(--bg) 45%); color: var(--text); font-family: "Segoe UI", Arial, sans-serif; display: grid; grid-template-columns: 1.2fr 0.8fr; }
  .stage { display: grid; place-items: center; perspective: 900px; overflow: hidden; }
  .board-wrap { transform-style: preserve-3d; transition: transform 80ms linear; }
  .board { width: 420px; height: 260px; background: linear-gradient(145deg, #166534, #22c55e); border: 4px solid #86efac; border-radius: 16px; box-shadow: 0 35px 80px rgba(0,0,0,.45); transform-style: preserve-3d; position: relative; }
  .chip { position: absolute; width: 86px; height: 86px; left: 167px; top: 87px; background: #111827; border: 2px solid #4b5563; border-radius: 10px; transform: translateZ(20px); }
  .sensor { position: absolute; width: 82px; height: 56px; right: 36px; top: 34px; background: #2563eb; border: 2px solid #93c5fd; border-radius: 8px; transform: translateZ(16px); }
  .gps { position: absolute; width: 92px; height: 66px; left: 34px; bottom: 34px; background: #eab308; border: 2px solid #fde68a; border-radius: 8px; transform: translateZ(16px); }
  .axis { position: absolute; font-weight: 700; color: #052e16; }
  .x { right: 14px; bottom: 12px; }
  .y { left: 14px; top: 12px; }
  .z { left: 196px; top: 10px; }
  aside { background: rgba(17,24,39,.74); border-left: 1px solid rgba(255,255,255,.08); padding: 28px; display: flex; flex-direction: column; gap: 18px; }
  h1 { margin: 0 0 8px; font-size: 24px; }
  .grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
  .card { background: rgba(31,41,55,.88); border: 1px solid rgba(255,255,255,.08); border-radius: 10px; padding: 14px; }
  .label { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .06em; }
  .value { font-size: 28px; font-weight: 700; margin-top: 4px; }
  .status { color: var(--accent); font-size: 14px; }
  canvas { width: 100%; height: 140px; background: rgba(31,41,55,.7); border-radius: 10px; }
  @media (max-width: 860px) { body { grid-template-columns: 1fr; } aside { border-left: 0; border-top: 1px solid rgba(255,255,255,.08); } .board { width: 320px; height: 200px; } }
</style>
</head>
<body>
  <main class="stage">
    <div id="wrap" class="board-wrap">
      <div class="board">
        <div class="chip"></div>
        <div class="sensor"></div>
        <div class="gps"></div>
        <div class="axis x">+X</div><div class="axis y">+Y</div><div class="axis z">+Z</div>
      </div>
    </div>
  </main>
  <aside>
    <div>
      <h1>实时姿态显示</h1>
      <div id="status" class="status">waiting</div>
    </div>
    <div class="grid">
      <div class="card"><div class="label">Roll</div><div id="roll" class="value">0.0°</div></div>
      <div class="card"><div class="label">Pitch</div><div id="pitch" class="value">0.0°</div></div>
      <div class="card"><div class="label">Yaw</div><div id="yaw" class="value">0.0°</div></div>
      <div class="card"><div class="label">Update</div><div id="hz" class="value">0.0 Hz</div></div>
    </div>
    <canvas id="chart" width="720" height="180"></canvas>
  </aside>
<script>
const wrap = document.getElementById('wrap');
const ids = ['roll','pitch','yaw','hz','status'];
const el = Object.fromEntries(ids.map(id => [id, document.getElementById(id)]));
const canvas = document.getElementById('chart'), ctx = canvas.getContext('2d');
let history = [];
function drawChart() {
  ctx.clearRect(0,0,canvas.width,canvas.height);
  ctx.strokeStyle = 'rgba(255,255,255,.12)';
  ctx.lineWidth = 1;
  for (let y=30; y<180; y+=30) { ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(720,y); ctx.stroke(); }
  const colors = ['#f97316','#38bdf8','#22c55e'];
  ['roll','pitch','yaw'].forEach((k, idx) => {
    ctx.strokeStyle = colors[idx]; ctx.lineWidth = 2; ctx.beginPath();
    history.forEach((p, i) => {
      const x = i * 720 / Math.max(1, history.length - 1);
      const y = 90 - Math.max(-90, Math.min(90, p[k])) * 0.85;
      if (i === 0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
    });
    ctx.stroke();
  });
}
async function tick() {
  try {
    const r = await fetch('/data', {cache:'no-store'});
    const d = await r.json();
    el.status.textContent = d.connected ? 'connected, serial lines: ' + d.serial_lines : d.message;
    el.roll.textContent = d.roll.toFixed(1) + '°';
    el.pitch.textContent = d.pitch.toFixed(1) + '°';
    el.yaw.textContent = d.yaw.toFixed(1) + '°';
    el.hz.textContent = d.update_hz.toFixed(1) + ' Hz';
    wrap.style.transform = `rotateZ(${d.yaw}deg) rotateX(${d.pitch}deg) rotateY(${-d.roll}deg)`;
    history.push({roll:d.roll, pitch:d.pitch, yaw:d.yaw});
    if (history.length > 240) history.shift();
    drawChart();
  } catch (e) {
    el.status.textContent = 'browser waiting for Python server';
  }
}
setInterval(tick, 50);
</script>
</body>
</html>
'''


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/data":
            body = json.dumps(LATEST).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        body = HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        return


def serial_worker():
    try:
        with serial.Serial(COM_PORT, BAUDRATE, timeout=1) as ser:
            LATEST["message"] = "uploading ESP32 attitude code"
            start_remote_code(ser, REMOTE_ATTITUDE_CODE)
            LATEST["message"] = "waiting for attitude stream"
            while True:
                line = ser.readline().decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                if line.startswith("ATT_WEB_ERROR"):
                    LATEST.update({"connected": False, "message": line})
                    continue
                if line.startswith("t_ms") or line == "ATT_WEB_BEGIN":
                    continue
                parts = line.split(",")
                if len(parts) != 6:
                    continue
                try:
                    LATEST.update({
                        "connected": True,
                        "message": "streaming",
                        "t_ms": int(parts[0]),
                        "roll": float(parts[1]),
                        "pitch": float(parts[2]),
                        "yaw": float(parts[3]),
                        "temp": float(parts[4]),
                        "update_hz": float(parts[5]),
                        "serial_lines": LATEST["serial_lines"] + 1,
                    })
                except ValueError:
                    continue
    except Exception as exc:
        LATEST.update({"connected": False, "message": "serial error: %s" % exc})


def main():
    print("Starting ESP32 real-time attitude web display")
    print("Serial port:", COM_PORT)
    print("Open: http://%s:%d" % (WEB_HOST, WEB_PORT))
    thread = threading.Thread(target=serial_worker, daemon=True)
    thread.start()
    server = ThreadingHTTPServer((WEB_HOST, WEB_PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
