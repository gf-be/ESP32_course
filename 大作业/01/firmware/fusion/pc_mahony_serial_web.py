"""
Mahony PI real-time web visualization.

Run this file on the computer with Thonny's local Python interpreter.

What this script does:
1. Sends temporary MicroPython code to ESP32 RAM through serial raw REPL.
2. ESP32 reads IMU + HMC5883L and runs Mahony PI attitude fusion in real time.
3. The PC script reads the live serial stream internally.
4. A local browser page renders a 3D attitude board.

Nothing is saved to ESP32 flash.

Open:
  http://127.0.0.1:8766
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
import json
import serial
import threading
import time


COM_PORT = "COM7"
BAUDRATE = 115200
WEB_HOST = "127.0.0.1"
WEB_PORT = 8766


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


REMOTE_MAHONY_CODE = r'''
from machine import Pin, I2C
import time
import struct
import math

SDA_PIN = 21
SCL_PIN = 22
I2C_FREQ = 400000
MPU_ADDR = 0x68
MAG_ADDR = 0x1E
TARGET_HZ = 100

GYRO_BIAS_X = 0.228303741
GYRO_BIAS_Y = 0.964654373
GYRO_BIAS_Z = -0.100939275

MAG_BIAS_X = 77.082135
MAG_BIAS_Y = -94.427834
MAG_BIAS_Z = -36.852085

MAG_M00 = 1.006948
MAG_M01 = -0.000000
MAG_M02 = 0.000000
MAG_M10 = -0.000000
MAG_M11 = 1.020430
MAG_M12 = 0.000000
MAG_M20 = 0.000000
MAG_M21 = 0.000000
MAG_M22 = 1.043697

KP = 1.2
KI = 0.02

def inv_sqrt(x):
    if x <= 0:
        return 0.0
    return 1.0 / math.sqrt(x)

def normalize3(x, y, z):
    n = inv_sqrt(x * x + y * y + z * z)
    if n == 0:
        return 0.0, 0.0, 0.0
    return x * n, y * n, z * n

def quat_mul(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    )

def quat_normalize(q):
    q0, q1, q2, q3 = q
    n = inv_sqrt(q0 * q0 + q1 * q1 + q2 * q2 + q3 * q3)
    if n == 0:
        return 1.0, 0.0, 0.0, 0.0
    return q0 * n, q1 * n, q2 * n, q3 * n

def quat_from_euler(roll_deg, pitch_deg, yaw_deg):
    r = math.radians(roll_deg) * 0.5
    p = math.radians(pitch_deg) * 0.5
    y = math.radians(yaw_deg) * 0.5
    cr = math.cos(r)
    sr = math.sin(r)
    cp = math.cos(p)
    sp = math.sin(p)
    cy = math.cos(y)
    sy = math.sin(y)
    return quat_normalize((
        cr * cp * cy + sr * sp * sy,
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
    ))

def euler_from_quat(q):
    q0, q1, q2, q3 = q
    roll = math.atan2(2.0 * (q0 * q1 + q2 * q3), 1.0 - 2.0 * (q1 * q1 + q2 * q2))
    s = 2.0 * (q0 * q2 - q3 * q1)
    if s > 1.0:
        s = 1.0
    elif s < -1.0:
        s = -1.0
    pitch = math.asin(s)
    yaw = math.atan2(2.0 * (q0 * q3 + q1 * q2), 1.0 - 2.0 * (q2 * q2 + q3 * q3))
    return math.degrees(roll), math.degrees(pitch), math.degrees(yaw)

def accel_angles(ax, ay, az):
    roll = math.degrees(math.atan2(ay, az))
    pitch = math.degrees(math.atan2(-ax, math.sqrt(ay * ay + az * az)))
    return roll, pitch

def mag_yaw(mx, my, mz, roll_deg, pitch_deg):
    roll = math.radians(roll_deg)
    pitch = math.radians(pitch_deg)
    mx2 = mx * math.cos(pitch) + mz * math.sin(pitch)
    my2 = mx * math.sin(roll) * math.sin(pitch) + my * math.cos(roll) - mz * math.sin(roll) * math.cos(pitch)
    return math.degrees(math.atan2(-my2, mx2))

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
    x -= MAG_BIAS_X
    y -= MAG_BIAS_Y
    z -= MAG_BIAS_Z
    cx = MAG_M00 * x + MAG_M01 * y + MAG_M02 * z
    cy = MAG_M10 * x + MAG_M11 * y + MAG_M12 * z
    cz = MAG_M20 * x + MAG_M21 * y + MAG_M22 * z
    return cx, cy, cz

class MahonyPI:
    def __init__(self, kp, ki):
        self.kp = kp
        self.ki = ki
        self.q = (1.0, 0.0, 0.0, 0.0)
        self.ix = 0.0
        self.iy = 0.0
        self.iz = 0.0
        self.initialized = False

    def init_from_acc_mag(self, ax, ay, az, mx, my, mz):
        ar, ap = accel_angles(ax, ay, az)
        ayaw = mag_yaw(mx, my, mz, ar, ap)
        self.q = quat_from_euler(ar, ap, ayaw)
        self.initialized = True

    def update(self, gx_dps, gy_dps, gz_dps, ax, ay, az, mx, my, mz, dt):
        ax, ay, az = normalize3(ax, ay, az)
        mx, my, mz = normalize3(mx, my, mz)
        if ax == 0 and ay == 0 and az == 0:
            return euler_from_quat(self.q)
        if not self.initialized:
            self.init_from_acc_mag(ax, ay, az, mx, my, mz)

        q0, q1, q2, q3 = self.q
        vx = 2.0 * (q1 * q3 - q0 * q2)
        vy = 2.0 * (q0 * q1 + q2 * q3)
        vz = q0 * q0 - q1 * q1 - q2 * q2 + q3 * q3

        h = quat_mul(self.q, quat_mul((0.0, mx, my, mz), (q0, -q1, -q2, -q3)))
        bx = math.sqrt(h[1] * h[1] + h[2] * h[2])
        bz = h[3]
        wx = 2.0 * bx * (0.5 - q2 * q2 - q3 * q3) + 2.0 * bz * (q1 * q3 - q0 * q2)
        wy = 2.0 * bx * (q1 * q2 - q0 * q3) + 2.0 * bz * (q0 * q1 + q2 * q3)
        wz = 2.0 * bx * (q0 * q2 + q1 * q3) + 2.0 * bz * (0.5 - q1 * q1 - q2 * q2)

        ex = (ay * vz - az * vy) + (my * wz - mz * wy)
        ey = (az * vx - ax * vz) + (mz * wx - mx * wz)
        ez = (ax * vy - ay * vx) + (mx * wy - my * wx)

        self.ix += ex * dt
        self.iy += ey * dt
        self.iz += ez * dt

        gx = math.radians(gx_dps) + self.kp * ex + self.ki * self.ix
        gy = math.radians(gy_dps) + self.kp * ey + self.ki * self.iy
        gz = math.radians(gz_dps) + self.kp * ez + self.ki * self.iz

        q_dot = quat_mul(self.q, (0.0, gx, gy, gz))
        self.q = quat_normalize((
            q0 + 0.5 * q_dot[0] * dt,
            q1 + 0.5 * q_dot[1] * dt,
            q2 + 0.5 * q_dot[2] * dt,
            q3 + 0.5 * q_dot[3] * dt,
        ))
        return euler_from_quat(self.q)

i2c = I2C(0, sda=Pin(SDA_PIN), scl=Pin(SCL_PIN), freq=I2C_FREQ)
scan = i2c.scan()
if MPU_ADDR not in scan or MAG_ADDR not in scan:
    print("MAHONY_WEB_ERROR,scan=" + ",".join(hex(x) for x in scan))
else:
    init_imu(i2c)
    init_mag(i2c)
    filt = MahonyPI(KP, KI)
    interval_ms = int(1000 / TARGET_HZ)
    next_t = time.ticks_ms()
    last_t = next_t
    fps_t0 = next_t
    fps_count = 0
    update_hz = 0.0
    print("MAHONY_WEB_BEGIN")
    print("t_ms,roll_deg,pitch_deg,yaw_deg,temp_c,update_hz")
    while True:
        now = time.ticks_ms()
        dt = max(0.001, time.ticks_diff(now, last_t) / 1000.0)
        last_t = now
        ax, ay, az, temp, gx, gy, gz = read_imu(i2c)
        mx, my, mz = read_mag(i2c)
        roll, pitch, yaw = filt.update(gx, gy, gz, ax, ay, az, mx, my, mz, dt)
        fps_count += 1
        elapsed = time.ticks_diff(now, fps_t0)
        if elapsed >= 1000:
            update_hz = fps_count * 1000.0 / elapsed
            fps_count = 0
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
<title>Mahony PI Attitude Display</title>
<style>
  :root { --bg:#0f172a; --panel:#172033; --text:#e5e7eb; --muted:#94a3b8; --accent:#38bdf8; }
  * { box-sizing: border-box; }
  body { margin:0; min-height:100vh; background:linear-gradient(135deg,#0f172a,#1e293b 55%,#111827); color:var(--text); font-family:"Segoe UI",Arial,sans-serif; display:grid; grid-template-columns:minmax(420px,1.2fr) minmax(340px,.8fr); }
  .stage { display:grid; place-items:center; perspective:900px; overflow:hidden; }
  .wrap { transform-style:preserve-3d; transition:transform 60ms linear; }
  .board { width:440px; height:270px; border-radius:14px; border:4px solid #86efac; background:linear-gradient(145deg,#15803d,#22c55e); box-shadow:0 32px 90px rgba(0,0,0,.55); position:relative; transform-style:preserve-3d; }
  .board:before { content:"ESP32 + MPU + HMC"; position:absolute; left:22px; top:18px; color:#052e16; font-weight:800; }
  .chip { position:absolute; width:92px; height:92px; left:174px; top:89px; border-radius:10px; background:#111827; border:2px solid #4b5563; transform:translateZ(22px); }
  .mag { position:absolute; width:92px; height:58px; right:34px; top:44px; border-radius:8px; background:#1d4ed8; border:2px solid #93c5fd; transform:translateZ(18px); }
  .gps { position:absolute; width:98px; height:68px; left:34px; bottom:36px; border-radius:8px; background:#eab308; border:2px solid #fde68a; transform:translateZ(18px); }
  .axis { position:absolute; color:#052e16; font-weight:900; }
  .x { right:16px; bottom:12px; } .y { left:16px; top:50px; } .z { left:205px; top:12px; }
  aside { padding:28px; background:rgba(15,23,42,.76); border-left:1px solid rgba(255,255,255,.08); display:flex; flex-direction:column; gap:18px; }
  h1 { margin:0; font-size:24px; }
  .status { color:var(--accent); font-size:14px; min-height:20px; }
  .grid { display:grid; grid-template-columns:repeat(2,1fr); gap:12px; }
  .card { background:rgba(23,32,51,.9); border:1px solid rgba(255,255,255,.08); border-radius:10px; padding:14px; }
  .label { color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.05em; }
  .value { margin-top:4px; font-size:28px; font-weight:800; }
  canvas { width:100%; height:170px; background:rgba(23,32,51,.9); border:1px solid rgba(255,255,255,.08); border-radius:10px; }
  .legend { display:flex; gap:14px; color:var(--muted); font-size:13px; }
  .dot { display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:5px; }
  @media(max-width:880px){ body{grid-template-columns:1fr;} aside{border-left:0;border-top:1px solid rgba(255,255,255,.08);} .board{width:330px;height:210px;} }
</style>
</head>
<body>
<main class="stage">
  <div id="wrap" class="wrap">
    <div class="board">
      <div class="chip"></div><div class="mag"></div><div class="gps"></div>
      <div class="axis x">+X</div><div class="axis y">+Y</div><div class="axis z">+Z</div>
    </div>
  </div>
</main>
<aside>
  <div><h1>Mahony PI 实时姿态</h1><div id="status" class="status">waiting</div></div>
  <div class="grid">
    <div class="card"><div class="label">Roll</div><div id="roll" class="value">0.0°</div></div>
    <div class="card"><div class="label">Pitch</div><div id="pitch" class="value">0.0°</div></div>
    <div class="card"><div class="label">Yaw</div><div id="yaw" class="value">0.0°</div></div>
    <div class="card"><div class="label">Update</div><div id="hz" class="value">0.0 Hz</div></div>
    <div class="card"><div class="label">Temp</div><div id="temp" class="value">0.0°C</div></div>
    <div class="card"><div class="label">Lines</div><div id="lines" class="value">0</div></div>
  </div>
  <canvas id="chart" width="760" height="220"></canvas>
  <div class="legend"><span><i class="dot" style="background:#f97316"></i>Roll</span><span><i class="dot" style="background:#38bdf8"></i>Pitch</span><span><i class="dot" style="background:#22c55e"></i>Yaw</span></div>
</aside>
<script>
const q = id => document.getElementById(id);
const wrap=q('wrap'), chart=q('chart'), ctx=chart.getContext('2d');
let hist=[];
function draw(){
  ctx.clearRect(0,0,chart.width,chart.height);
  ctx.strokeStyle='rgba(255,255,255,.12)'; ctx.lineWidth=1;
  for(let y=35;y<220;y+=35){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(760,y);ctx.stroke();}
  [['roll','#f97316'],['pitch','#38bdf8'],['yaw','#22c55e']].forEach(([k,c])=>{
    ctx.strokeStyle=c; ctx.lineWidth=2; ctx.beginPath();
    hist.forEach((p,i)=>{let x=i*760/Math.max(1,hist.length-1); let y=110-Math.max(-90,Math.min(90,p[k]))*1.05; if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);});
    ctx.stroke();
  });
}
async function tick(){
  try{
    const d=await (await fetch('/data',{cache:'no-store'})).json();
    q('status').textContent=d.connected?'connected, '+d.message:d.message;
    q('roll').textContent=d.roll.toFixed(1)+'°'; q('pitch').textContent=d.pitch.toFixed(1)+'°'; q('yaw').textContent=d.yaw.toFixed(1)+'°';
    q('hz').textContent=d.update_hz.toFixed(1)+' Hz'; q('temp').textContent=d.temp.toFixed(1)+'°C'; q('lines').textContent=d.serial_lines;
    wrap.style.transform=`rotateZ(${d.yaw}deg) rotateX(${d.pitch}deg) rotateY(${-d.roll}deg)`;
    hist.push({roll:d.roll,pitch:d.pitch,yaw:d.yaw}); if(hist.length>260)hist.shift(); draw();
  }catch(e){ q('status').textContent='waiting for Python web server'; }
}
setInterval(tick,50);
</script>
</body>
</html>
'''


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
    time.sleep(0.3)
    ser.reset_input_buffer()
    ser.write(b"\x01")
    read_until(ser, b">", timeout=5)


def start_remote_code(ser, code):
    enter_raw_repl(ser)
    data = code.encode("utf-8")
    for i in range(0, len(data), 128):
        ser.write(data[i:i + 128])
        time.sleep(0.005)
    ser.write(b"\x04")
    read_until(ser, b"OK", timeout=5)


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


def parse_line(line):
    parts = line.strip().split(",")
    if len(parts) != 6:
        return False
    try:
        t_ms = int(parts[0])
        roll = float(parts[1])
        pitch = float(parts[2])
        yaw = float(parts[3])
        temp = float(parts[4])
        hz = float(parts[5])
    except ValueError:
        return False
    LATEST.update({
        "connected": True,
        "t_ms": t_ms,
        "roll": roll,
        "pitch": pitch,
        "yaw": yaw,
        "temp": temp,
        "update_hz": hz,
        "serial_lines": LATEST["serial_lines"] + 1,
        "message": "ESP32 sensors -> Mahony PI -> web",
    })
    return True


def serial_worker():
    while True:
        try:
            with serial.Serial(COM_PORT, BAUDRATE, timeout=1) as ser:
                LATEST.update({"connected": False, "message": "uploading temporary ESP32 Mahony code"})
                start_remote_code(ser, REMOTE_MAHONY_CODE)
                LATEST.update({"connected": False, "message": "ESP32 code running, waiting for sensor stream"})
                while True:
                    line = ser.readline().decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    if line.startswith("MAHONY_WEB_ERROR"):
                        LATEST.update({"connected": False, "message": line})
                        continue
                    if line.startswith("t_ms") or line == "MAHONY_WEB_BEGIN":
                        continue
                    parse_line(line)
        except Exception as exc:
            LATEST.update({"connected": False, "message": "serial error: %s" % exc})
            time.sleep(2)


def main():
    print("Mahony PI sensor-to-web visualization")
    print("Serial port:", COM_PORT)
    print("Open: http://%s:%d" % (WEB_HOST, WEB_PORT))
    print("Close Thonny's ESP32 shell first if the serial port is busy.")
    threading.Thread(target=serial_worker, daemon=True).start()
    server = ThreadingHTTPServer((WEB_HOST, WEB_PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
