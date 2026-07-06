"""
Analyze real-time ESP32 ESKF15 capture data.

Input:
  data/fusion_comparison/eskf_realtime/eskf15_realtime_*.csv

Outputs:
  data/analysis/eskf_15d_realtime_summary_*.csv
  data/figures/eskf_15d_realtime_track_*.png
  data/figures/eskf_15d_realtime_error_*.png
"""

from pathlib import Path
import csv
import math
import statistics

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


EARTH_R = 6378137.0


def project_root():
    return Path(__file__).resolve().parents[2]


def latest_file(folder, pattern):
    files = sorted(folder.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def to_float(value, default=float("nan")):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def to_int(value, default=0):
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def finite_values(rows, key):
    out = []
    for row in rows:
        value = to_float(row.get(key))
        if math.isfinite(value):
            out.append(value)
    return out


def pct(values, q):
    vals = sorted(v for v in values if math.isfinite(v))
    if not vals:
        return float("nan")
    idx = int(math.ceil(q * len(vals))) - 1
    idx = max(0, min(idx, len(vals) - 1))
    return vals[idx]


def median(values):
    vals = [v for v in values if math.isfinite(v)]
    return statistics.median(vals) if vals else float("nan")


def mean(values):
    vals = [v for v in values if math.isfinite(v)]
    return statistics.fmean(vals) if vals else float("nan")


def valid_lat_lon(lat, lon):
    return math.isfinite(lat) and math.isfinite(lon) and abs(lat) > 1e-9 and abs(lon) > 1e-9


def haversine_m(lat1, lon1, lat2, lon2):
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2.0 * EARTH_R * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))


def lla_points(rows, lat_key, lon_key):
    pts = []
    for row in rows:
        lat = to_float(row.get(lat_key))
        lon = to_float(row.get(lon_key))
        if valid_lat_lon(lat, lon):
            pts.append((lat, lon))
    return pts


def lla_distance(points):
    total = 0.0
    for i in range(1, len(points)):
        total += haversine_m(points[i - 1][0], points[i - 1][1], points[i][0], points[i][1])
    return total


def xy_distance(rows, x_key, y_key):
    total = 0.0
    prev = None
    for row in rows:
        x = to_float(row.get(x_key))
        y = to_float(row.get(y_key))
        if not (math.isfinite(x) and math.isfinite(y)):
            continue
        if prev is not None:
            total += math.hypot(x - prev[0], y - prev[1])
        prev = (x, y)
    return total


def nearest_track_errors(points, reference):
    errors = []
    if not points or not reference:
        return errors
    for lat, lon in points:
        best = None
        for rlat, rlon in reference:
            d = haversine_m(lat, lon, rlat, rlon)
            if best is None or d < best:
                best = d
        if best is not None:
            errors.append(best)
    return errors


def local_xy(points, lat0, lon0):
    out = []
    c = math.cos(math.radians(lat0))
    for lat, lon in points:
        x = math.radians(lon - lon0) * EARTH_R * c
        y = math.radians(lat - lat0) * EARTH_R
        out.append((x, y))
    return out


def row_time_s(rows):
    ts = [to_float(row.get("t_ms")) for row in rows]
    ts = [t for t in ts if math.isfinite(t)]
    if not ts:
        return []
    t0 = ts[0]
    return [(t - t0) / 1000.0 for t in ts]


def save_summary(path, items):
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["item", "value", "unit", "note"])
        for row in items:
            writer.writerow(row)


def plot_track(fig_path, gps_pts, est_pts, phone_pts):
    all_pts = []
    for pts in (phone_pts, gps_pts, est_pts):
        all_pts.extend(pts)
    if not all_pts:
        return False

    lat0, lon0 = all_pts[0]
    plt.figure(figsize=(8.5, 7.0))
    ax = plt.gca()
    if phone_pts:
        xy = local_xy(phone_pts, lat0, lon0)
        ax.plot([p[0] for p in xy], [p[1] for p in xy], label="phone GNSS reference", linewidth=2.0)
    if gps_pts:
        xy = local_xy(gps_pts, lat0, lon0)
        ax.plot([p[0] for p in xy], [p[1] for p in xy], label="ESP32 GPS measurement", linewidth=1.5, alpha=0.8)
    if est_pts:
        xy = local_xy(est_pts, lat0, lon0)
        ax.plot([p[0] for p in xy], [p[1] for p in xy], label="real-time 15D ESKF estimate", linewidth=1.8)
    ax.set_xlabel("East / m")
    ax.set_ylabel("North / m")
    ax.set_title("Real-time 15D ESKF trajectory overlay")
    ax.axis("equal")
    ax.grid(True, alpha=0.3)
    ax.legend()
    plt.tight_layout()
    plt.savefig(fig_path, dpi=180)
    plt.close()
    return True


def plot_error(fig_path, rows):
    if not rows:
        return False
    t = row_time_s(rows)
    if not t:
        t = list(range(len(rows)))
    innov = finite_values(rows, "innov_xy_m")
    sigma_e = finite_values(rows, "sigma_e_m")
    sigma_n = finite_values(rows, "sigma_n_m")
    imu_hz = finite_values(rows, "imu_hz")

    n = min(len(t), len(rows))
    x = t[:n]
    innov = [to_float(rows[i].get("innov_xy_m")) for i in range(n)]
    sigma_e = [to_float(rows[i].get("sigma_e_m")) for i in range(n)]
    sigma_n = [to_float(rows[i].get("sigma_n_m")) for i in range(n)]
    imu_hz = [to_float(rows[i].get("imu_hz")) for i in range(n)]

    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    axes[0].plot(x, innov, label="GPS innovation XY", linewidth=1.2)
    axes[0].plot(x, sigma_e, label="sigma east", linewidth=1.1)
    axes[0].plot(x, sigma_n, label="sigma north", linewidth=1.1)
    axes[0].set_ylabel("m")
    axes[0].set_title("Real-time 15D ESKF innovation and covariance")
    axes[0].grid(True, alpha=0.3)
    axes[0].legend()

    axes[1].plot(x, imu_hz, label="measured IMU/ESKF loop rate", linewidth=1.2)
    axes[1].axhline(100.0, color="tab:red", linestyle="--", linewidth=1.0, label="100 Hz target")
    axes[1].set_xlabel("Time / s")
    axes[1].set_ylabel("Hz")
    axes[1].grid(True, alpha=0.3)
    axes[1].legend()
    plt.tight_layout()
    plt.savefig(fig_path, dpi=180)
    plt.close(fig)
    return True


def main():
    root = project_root()
    in_dir = root / "data" / "fusion_comparison" / "eskf_realtime"
    analysis_dir = root / "data" / "analysis"
    fig_dir = root / "data" / "figures"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    fig_dir.mkdir(parents=True, exist_ok=True)

    src = latest_file(in_dir, "eskf15_realtime_*.csv")
    if src is None:
        raise SystemExit("No real-time ESKF CSV found in %s" % in_dir)

    rows = read_csv(src)
    stamp = src.stem.replace("eskf15_realtime_", "")
    phone_src = latest_file(analysis_dir, "gps_phone_reference_points_*.csv")
    phone_rows = read_csv(phone_src) if phone_src else []

    initialized = [row for row in rows if to_int(row.get("initialized")) == 1]
    gps_pts = lla_points(rows, "gps_lat", "gps_lon")
    est_pts = lla_points(initialized, "est_lat", "est_lon")
    phone_pts = lla_points(phone_rows, "lat", "lon")

    times = [to_float(row.get("t_ms")) for row in rows if math.isfinite(to_float(row.get("t_ms")))]
    duration = (times[-1] - times[0]) / 1000.0 if len(times) >= 2 else float("nan")
    imu_hz = finite_values(rows, "imu_hz")
    innovations = finite_values(initialized, "innov_xy_m")
    gps_updates = [to_int(row.get("gps_updates")) for row in rows]
    gps_rejects = [to_int(row.get("gps_rejects")) for row in rows]
    sats = finite_values(rows, "satellites")
    hdop = finite_values(rows, "hdop")
    sigma_e = finite_values(initialized, "sigma_e_m")
    sigma_n = finite_values(initialized, "sigma_n_m")

    gps_ref_err = nearest_track_errors(gps_pts, phone_pts)
    est_ref_err = nearest_track_errors(est_pts, phone_pts)

    summary = [
        ("source_csv", str(src), "", "latest real-time ESP32 ESKF capture"),
        ("rows", len(rows), "rows", ""),
        ("initialized_rows", len(initialized), "rows", "initialized=1 means ENU origin is ready"),
        ("duration", duration, "s", ""),
        ("target_loop_rate", 100.0, "Hz", "ESP32 main loop target"),
        ("imu_hz_mean", mean(imu_hz), "Hz", "measured by ESP32"),
        ("imu_hz_median", median(imu_hz), "Hz", "measured by ESP32"),
        ("satellites_median", median(sats), "sat", ""),
        ("hdop_median", median(hdop), "", ""),
        ("gps_updates_final", gps_updates[-1] if gps_updates else 0, "updates", ""),
        ("gps_rejects_final", gps_rejects[-1] if gps_rejects else 0, "updates", "large-innovation gate rejects"),
        ("gps_measurement_distance", lla_distance(gps_pts), "m", "distance from ESP32 GPS measurements"),
        ("eskf_estimated_distance_latlon", lla_distance(est_pts), "m", "distance from ESKF estimated lat/lon"),
        ("eskf_estimated_distance_enu", xy_distance(initialized, "e_m", "n_m"), "m", "distance from ESKF ENU state"),
        ("innovation_xy_median", median(innovations), "m", ""),
        ("innovation_xy_p95", pct(innovations, 0.95), "m", ""),
        ("sigma_e_final", sigma_e[-1] if sigma_e else float("nan"), "m", ""),
        ("sigma_n_final", sigma_n[-1] if sigma_n else float("nan"), "m", ""),
        ("phone_reference", str(phone_src) if phone_src else "", "", "optional spatial reference track"),
        ("gps_to_phone_nearest_median", median(gps_ref_err), "m", "nearest spatial distance, not time-synchronized"),
        ("gps_to_phone_nearest_p95", pct(gps_ref_err, 0.95), "m", "nearest spatial distance, not time-synchronized"),
        ("eskf_to_phone_nearest_median", median(est_ref_err), "m", "nearest spatial distance, not time-synchronized"),
        ("eskf_to_phone_nearest_p95", pct(est_ref_err, 0.95), "m", "nearest spatial distance, not time-synchronized"),
    ]

    summary_path = analysis_dir / ("eskf_15d_realtime_summary_%s.csv" % stamp)
    track_path = fig_dir / ("eskf_15d_realtime_track_%s.png" % stamp)
    error_path = fig_dir / ("eskf_15d_realtime_error_%s.png" % stamp)

    save_summary(summary_path, summary)
    plot_track(track_path, gps_pts, est_pts, phone_pts)
    plot_error(error_path, rows)

    print("Analyzed:", src)
    print("Summary:", summary_path)
    print("Track figure:", track_path)
    print("Error figure:", error_path)
    print("Rows:", len(rows), "initialized:", len(initialized))
    print("Mean IMU Hz: %.2f" % mean(imu_hz))
    print("Innovation median/p95: %.2f / %.2f m" % (median(innovations), pct(innovations, 0.95)))


if __name__ == "__main__":
    main()
