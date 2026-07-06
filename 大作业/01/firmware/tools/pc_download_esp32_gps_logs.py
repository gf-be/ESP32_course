"""
Download offline GPS logs from ESP32 /gps_logs to the project data folder.

Use this after outdoor power-bank collection. Stop Thonny Shell first if COM4
is busy. This script reads text logs only and does not delete files on ESP32.
"""

from datetime import datetime
from pathlib import Path
import serial
import time


COM_PORT = "COM4"
BAUDRATE = 115200
REMOTE_DIR = "/gps_logs"


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
    time.sleep(0.4)
    ser.reset_input_buffer()
    ser.write(b"\x01")
    read_until(ser, b">", timeout=5)


def exit_raw_repl(ser):
    ser.write(b"\x02")
    time.sleep(0.2)


def exec_raw(ser, code, timeout=60):
    data = code.encode("utf-8")
    for i in range(0, len(data), 128):
        ser.write(data[i:i + 128])
        time.sleep(0.005)
    ser.write(b"\x04")
    read_until(ser, b"OK", timeout=timeout)
    out = read_until(ser, b"\x04", timeout=timeout).replace(b"\x04", b"")
    err = read_until(ser, b"\x04", timeout=timeout).replace(b"\x04", b"")
    if err.strip():
        raise RuntimeError(err.decode("utf-8", errors="replace"))
    return out


def list_logs(ser):
    code = r'''
import os
d = __REMOTE_DIR__
try:
    names = os.listdir(d)
except OSError:
    names = []
for name in names:
    path = d + "/" + name
    try:
        print("%s,%d" % (path, os.stat(path)[6]))
    except OSError:
        pass
'''
    out = exec_raw(ser, code.replace("__REMOTE_DIR__", repr(REMOTE_DIR)), timeout=20)
    result = []
    for raw_line in out.decode("utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or "," not in line:
            continue
        path, size_text = line.rsplit(",", 1)
        try:
            size = int(size_text)
        except ValueError:
            size = -1
        result.append((path, size))
    return result


def download_log(ser, remote_path, size):
    code = r'''
import sys
f = open(__PATH__, "r")
while True:
    chunk = f.read(512)
    if not chunk:
        break
    sys.stdout.write(chunk)
f.close()
'''
    timeout = max(30, int(size / 4500) + 20) if size > 0 else 30
    return exec_raw(ser, code.replace("__PATH__", repr(remote_path)), timeout=timeout)


def main():
    project_root = Path(__file__).resolve().parents[2]
    out_dir = project_root / "data" / "gps" / ("offline_esp32_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Download ESP32 offline GPS logs")
    print("Port:", COM_PORT)
    print("Output:", out_dir)

    with serial.Serial(COM_PORT, BAUDRATE, timeout=1) as ser:
        enter_raw_repl(ser)
        logs = list_logs(ser)
        print("logs:", len(logs))
        for index, (remote_path, size) in enumerate(logs, start=1):
            print("download %d/%d: %s (%d bytes)" % (index, len(logs), remote_path, size))
            data = download_log(ser, remote_path, size)
            local_path = out_dir / Path(remote_path).name
            local_path.write_bytes(data)
        exit_raw_repl(ser)

    print("Done.")
    print("Saved to:", out_dir)


if __name__ == "__main__":
    main()
