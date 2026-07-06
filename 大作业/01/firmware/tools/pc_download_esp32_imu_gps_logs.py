"""
Download ESP32 offline IMU + GPS logs from /imu_gps_logs.

Use this after power-bank outdoor collection. The script stops the running
/main.py, downloads the largest recorded session, and merges its CSV chunks into
data/fusion_comparison/imu_gps_sync/imu_gps_sync_offline_*.csv for analysis.
"""

from datetime import datetime
from pathlib import Path
import re
import serial
import time


COM_PORT = "COM4"
BAUDRATE = 115200
REMOTE_DIR = "/imu_gps_logs"
MANUAL_SESSION_ID = None
DELETE_AFTER_DOWNLOAD = False

SESSION_RE = re.compile(r"^imu_gps_sync_(\d{4})_(\d{2})\.csv$")


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
        print("%s,%d" % (name, os.stat(path)[6]))
    except OSError:
        pass
'''
    out = exec_raw(ser, code.replace("__REMOTE_DIR__", repr(REMOTE_DIR)), timeout=20)
    result = []
    for raw_line in out.decode("utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or "," not in line:
            continue
        name, size_text = line.rsplit(",", 1)
        match = SESSION_RE.match(name)
        if not match:
            continue
        try:
            size = int(size_text)
        except ValueError:
            size = -1
        result.append({
            "name": name,
            "path": REMOTE_DIR + "/" + name,
            "session": int(match.group(1)),
            "part": int(match.group(2)),
            "size": size,
        })
    result.sort(key=lambda item: (item["session"], item["part"]))
    return result


def group_sessions(logs):
    grouped = {}
    for item in logs:
        grouped.setdefault(item["session"], []).append(item)
    for files in grouped.values():
        files.sort(key=lambda item: item["part"])
    return grouped


def select_session(grouped):
    if MANUAL_SESSION_ID is not None:
        if MANUAL_SESSION_ID not in grouped:
            raise RuntimeError("Session %s was not found on ESP32." % MANUAL_SESSION_ID)
        return MANUAL_SESSION_ID, grouped[MANUAL_SESSION_ID]

    best_session = None
    best_size = -1
    for session, files in grouped.items():
        total_size = sum(max(item["size"], 0) for item in files)
        if total_size > best_size:
            best_size = total_size
            best_session = session
    if best_session is None:
        raise RuntimeError("No imu_gps_sync_*.csv logs found under %s." % REMOTE_DIR)
    return best_session, grouped[best_session]


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
    timeout = max(30, int(size / 3500) + 30) if size > 0 else 30
    return exec_raw(ser, code.replace("__PATH__", repr(remote_path)), timeout=timeout)


def delete_remote_logs(ser, files):
    for item in files:
        code = "import os\nos.remove(%r)\n" % item["path"]
        exec_raw(ser, code, timeout=20)


def merge_csv(raw_paths, merged_path):
    wrote_header = False
    rows = 0
    with merged_path.open("w", encoding="utf-8", newline="") as out:
        out.write("# Merged ESP32 offline IMU GPS sync chunks\n")
        for raw_path in raw_paths:
            with raw_path.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if not line.strip() or line.startswith("#"):
                        continue
                    if line.startswith("t_ms,"):
                        if not wrote_header:
                            out.write(line)
                            wrote_header = True
                        continue
                    if not wrote_header:
                        continue
                    out.write(line)
                    rows += 1
    return rows


def main():
    project_root = Path(__file__).resolve().parents[2]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    sync_dir = project_root / "data" / "fusion_comparison" / "imu_gps_sync"
    raw_dir = sync_dir / ("offline_esp32_" + stamp)
    raw_dir.mkdir(parents=True, exist_ok=True)
    merged_path = sync_dir / ("imu_gps_sync_offline_" + stamp + ".csv")

    print("Download ESP32 offline IMU + GPS logs")
    print("Port:", COM_PORT)
    print("Remote:", REMOTE_DIR)
    print("Raw output:", raw_dir)

    with serial.Serial(COM_PORT, BAUDRATE, timeout=1) as ser:
        enter_raw_repl(ser)
        logs = list_logs(ser)
        grouped = group_sessions(logs)

        print("sessions:")
        for session, files in sorted(grouped.items()):
            total_size = sum(max(item["size"], 0) for item in files)
            print("  %04d: parts=%d, bytes=%d" % (session, len(files), total_size))

        session, files = select_session(grouped)
        print("selected_session: %04d" % session)

        raw_paths = []
        for index, item in enumerate(files, start=1):
            print(
                "download %d/%d: %s (%d bytes)"
                % (index, len(files), item["path"], item["size"])
            )
            data = download_log(ser, item["path"], item["size"])
            local_path = raw_dir / item["name"]
            local_path.write_bytes(data)
            raw_paths.append(local_path)

        if DELETE_AFTER_DOWNLOAD:
            delete_remote_logs(ser, files)
            print("remote selected session deleted")

        exit_raw_repl(ser)

    rows = merge_csv(raw_paths, merged_path)
    print("Done.")
    print("Merged rows:", rows)
    print("Merged CSV:", merged_path)
    print("Raw chunks:", raw_dir)
    print("Next analysis script: analyze_eskf_15d_sync.py")


if __name__ == "__main__":
    main()
