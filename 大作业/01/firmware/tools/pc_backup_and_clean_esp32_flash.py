"""
Back up old ESP32 log files to the computer, then clean ESP32 flash.

This is intended before installing a new /main.py when MicroPython reports
OSError 28 (no space left on device).
"""

from datetime import datetime
from pathlib import Path
import serial
import time


COM_PORT = "COM4"
BAUDRATE = 115200

BACKUP_TARGETS = ["/gps_logs", "/gps_baro_logs"]
REMOVE_TARGETS = [
    "/autorun_target.txt",
    "/bmp280_patch_points.py",
    "/bmp280_staircase.py",
    "/bmp280_stair",
    "/gps_baro_fusion.py",
    "/gps_baro_logs",
    "/gps_logs",
    "/main.py",
    "/main_gps_autorun_backup.py",
]


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


def exec_raw(ser, code, timeout=30):
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


def list_backup_files(ser):
    code = r'''
import os
TARGETS = __TARGETS__

def is_dir(path):
    try:
        os.listdir(path)
        return True
    except OSError:
        return False

def walk(path):
    if is_dir(path):
        for name in os.listdir(path):
            child = path + "/" + name if path != "/" else "/" + name
            walk(child)
    else:
        try:
            print("%s,%d" % (path, os.stat(path)[6]))
        except OSError:
            pass

for target in TARGETS:
    walk(target)
'''
    out = exec_raw(ser, code.replace("__TARGETS__", repr(BACKUP_TARGETS)), timeout=30)
    files = []
    for raw_line in out.decode("utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or "," not in line:
            continue
        path, size_text = line.rsplit(",", 1)
        try:
            size = int(size_text)
        except ValueError:
            size = -1
        files.append((path, size))
    return files


def download_file(ser, remote_path, local_path, size):
    code = r'''
import sys
p = __PATH__
f = open(p, "r")
while True:
    chunk = f.read(512)
    if not chunk:
        break
    sys.stdout.write(chunk)
f.close()
'''
    timeout = max(30, int(size / 4500) + 20) if size > 0 else 30
    data = exec_raw(ser, code.replace("__PATH__", repr(remote_path)), timeout=timeout)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_bytes(data)


def clean_flash(ser):
    code = r'''
import os
REMOVE_TARGETS = __REMOVE_TARGETS__

def is_dir(path):
    try:
        os.listdir(path)
        return True
    except OSError:
        return False

def remove_path(path):
    if is_dir(path):
        for name in os.listdir(path):
            child = path + "/" + name if path != "/" else "/" + name
            remove_path(child)
        try:
            os.rmdir(path)
            print("removed_dir,%s" % path)
        except OSError as exc:
            print("skip_dir,%s,%r" % (path, exc))
    else:
        try:
            os.remove(path)
            print("removed_file,%s" % path)
        except OSError as exc:
            print("skip_file,%s,%r" % (path, exc))

for target in REMOVE_TARGETS:
    if target == "/boot.py":
        print("keep,/boot.py")
    else:
        remove_path(target)

try:
    st = os.statvfs("/")
    block_size = st[0]
    print("FLASH,total,%d,free,%d" % (st[2] * block_size, st[3] * block_size))
except Exception as exc:
    print("FLASH,error,%r" % (exc,))
print("after_files,%r" % (os.listdir(),))
'''
    out = exec_raw(ser, code.replace("__REMOVE_TARGETS__", repr(REMOVE_TARGETS)), timeout=60)
    return out.decode("utf-8", errors="replace")


def main():
    project_root = Path(__file__).resolve().parents[2]
    backup_root = (
        project_root
        / "data"
        / "esp32_flash_backup"
        / datetime.now().strftime("gps_autorun_before_clean_%Y%m%d_%H%M%S")
    )
    print("ESP32 flash backup and clean")
    print("Port:", COM_PORT)
    print("Backup root:", backup_root)

    with serial.Serial(COM_PORT, BAUDRATE, timeout=1) as ser:
        enter_raw_repl(ser)
        files = list_backup_files(ser)
        print("Files to back up:", len(files))
        for index, (remote_path, size) in enumerate(files, start=1):
            local_path = backup_root / remote_path.lstrip("/")
            print("backup %d/%d: %s (%d bytes)" % (index, len(files), remote_path, size))
            download_file(ser, remote_path, local_path, size)
        manifest = backup_root / "manifest.txt"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            "\n".join("%s,%d" % item for item in files) + "\n",
            encoding="utf-8",
        )
        print("Backup finished.")
        print(clean_flash(ser))
        exit_raw_repl(ser)

    print("Done.")


if __name__ == "__main__":
    main()
