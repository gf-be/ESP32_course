"""
Capture real-time ESKF15 serial output from ESP32 and save CSV on the computer.

Run this with local Python after installing esp32_eskf_15d_realtime_main.py to
the ESP32. Close Thonny Shell first if COM4 is busy.
"""

from pathlib import Path
from datetime import datetime
import csv
import serial
import time


COM_PORT = "COM4"
BAUDRATE = 115200
DURATION_S = 600

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


def main():
    project_root = Path(__file__).resolve().parents[2]
    out_dir = project_root / "data" / "fusion_comparison" / "eskf_realtime"
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / ("eskf15_realtime_%s.csv" % timestamp)

    print("Capture ESP32 real-time 15D ESKF")
    print("Port:", COM_PORT)
    print("Duration:", DURATION_S, "s")
    print("Output:", out_path)
    print("Tip: wait outdoors until initialized becomes 1.")

    rows = 0
    start = time.time()
    with serial.Serial(COM_PORT, BAUDRATE, timeout=1) as ser, out_path.open(
        "w", newline="", encoding="utf-8-sig"
    ) as f:
        writer = csv.writer(f)
        writer.writerow(HEADERS)
        while time.time() - start < DURATION_S:
            raw = ser.readline()
            if not raw:
                continue
            line = raw.decode("utf-8", errors="replace").strip()
            if line:
                print(line)
            if not line.startswith("ESKF15,"):
                continue
            parts = line.split(",")
            values = parts[1:]
            if len(values) != len(HEADERS):
                print("skip malformed ESKF15 line, fields=", len(values))
                continue
            writer.writerow(values)
            rows += 1
            if rows % 25 == 0:
                f.flush()

    print("")
    print("Saved rows:", rows)
    print("CSV:", out_path)


if __name__ == "__main__":
    main()
