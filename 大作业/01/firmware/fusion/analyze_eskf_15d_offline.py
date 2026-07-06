# -*- coding: utf-8 -*-
"""
Offline 15-state simplified ESKF for GPS trajectory smoothing.

This script is the course-report version of a 15-dimensional error-state
Kalman filter:

  error state dx = [dp(3), dv(3), dtheta(3), dbg(3), dba(3)]^T
  nominal state  = [p(3), v(3), q(4), bg(3), ba(3)]

Current input uses the existing ESP32 GPS offline track. Because the available
outdoor walk does not contain synchronized IMU samples, prediction falls back
to a zero-acceleration / constant-velocity inertial model. The attitude and bias
states are still present in the 15D covariance and injection pipeline, so a
future synchronized IMU+GPS log can use the same structure by replacing the
predict() input with calibrated ax/ay/az and gx/gy/gz.

Inputs:
  data/analysis/gps_track_points_offline_*.csv
  data/analysis/gps_phone_reference_points_20260629.csv

Outputs:
  data/analysis/eskf_15d_offline_states_20260629.csv
  data/analysis/eskf_15d_offline_summary_20260629.csv
  data/figures/eskf_15d_track_overlay_20260629.png
  data/figures/eskf_15d_error_compare_20260629.png
  data/figures/eskf_15d_innovation_20260629.png
  data/figures/eskf_15d_track_overlay_20260629.html
"""

from pathlib import Path
import csv
import math
import statistics

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
ANALYSIS_DIR = ROOT / "data" / "analysis"
FIG_DIR = ROOT / "data" / "figures"
TAG = "20260629"

QUALITY_MIN_SATS = 4
QUALITY_MAX_HDOP = 5.0


def deg2rad(x):
    return x * math.pi / 180.0


def rad2deg(x):
    return x * 180.0 / math.pi


def haversine_m(a, b):
    lat1, lon1 = a
    lat2, lon2 = b
    radius = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.atan2(math.sqrt(x), math.sqrt(1 - x))


def percentile(values, pct):
    if not values:
        return float("nan")
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * pct))))
    return ordered[index]


def path_distance_latlon(points):
    return sum(
        haversine_m((a["lat"], a["lon"]), (b["lat"], b["lon"]))
        for a, b in zip(points[:-1], points[1:])
    )


def path_distance_enu(points):
    return sum(
        float(np.linalg.norm(b["p_enu"][:2] - a["p_enu"][:2]))
        for a, b in zip(points[:-1], points[1:])
    )


def latest_gps_points_file():
    files = sorted(ANALYSIS_DIR.glob("gps_track_points_offline_*.csv"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise FileNotFoundError("No gps_track_points_offline_*.csv found in %s" % ANALYSIS_DIR)
    return files[-1]


def read_gps_points(path):
    rows = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                rows.append({
                    "source_file": row.get("source_file", ""),
                    "file_index": int(float(row.get("file_index", 0) or 0)),
                    "elapsed_ms": int(float(row.get("elapsed_ms", 0) or 0)),
                    "lat": float(row["lat"]),
                    "lon": float(row["lon"]),
                    "alt_m": float(row.get("alt_m", "nan") or "nan"),
                    "satellites": int(float(row.get("satellites", 0) or 0)),
                    "hdop": float(row.get("hdop", "nan") or "nan"),
                    "speed_knots": float(row.get("speed_knots", "nan") or "nan"),
                })
            except Exception:
                continue
    rows.sort(key=lambda p: (p["file_index"], p["elapsed_ms"]))

    offset = 0.0
    last_file = None
    last_elapsed = 0.0
    for row in rows:
        if last_file is None:
            last_file = row["source_file"]
        if row["source_file"] != last_file:
            offset += last_elapsed
            last_file = row["source_file"]
        last_elapsed = row["elapsed_ms"] / 1000.0
        row["t_s"] = offset + row["elapsed_ms"] / 1000.0
    return rows


def read_phone_reference():
    path = ANALYSIS_DIR / ("gps_phone_reference_points_%s.csv" % TAG)
    if not path.exists():
        raise FileNotFoundError("Phone reference CSV not found: %s" % path)
    rows = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                rows.append({
                    "lat": float(row["lat"]),
                    "lon": float(row["lon"]),
                    "elapsed_s": float(row.get("elapsed_s", "nan") or "nan"),
                    "ele_m": float(row.get("ele_m", "nan") or "nan"),
                })
            except Exception:
                continue
    return rows


class LocalFrame:
    def __init__(self, lat0, lon0, alt0=0.0):
        self.lat0 = lat0
        self.lon0 = lon0
        self.alt0 = alt0
        self.r_earth = 6378137.0
        self.cos_lat0 = math.cos(deg2rad(lat0))

    def lla_to_enu(self, lat, lon, alt=0.0):
        east = deg2rad(lon - self.lon0) * self.r_earth * self.cos_lat0
        north = deg2rad(lat - self.lat0) * self.r_earth
        up = alt - self.alt0 if not math.isnan(alt) else 0.0
        return np.array([east, north, up], dtype=float)

    def enu_to_lla(self, enu):
        lat = self.lat0 + rad2deg(enu[1] / self.r_earth)
        lon = self.lon0 + rad2deg(enu[0] / (self.r_earth * self.cos_lat0))
        alt = self.alt0 + enu[2]
        return lat, lon, alt


def quat_normalize(q):
    n = float(np.linalg.norm(q))
    if n <= 0:
        return np.array([1.0, 0.0, 0.0, 0.0])
    return q / n


def quat_mul(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return np.array([
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    ], dtype=float)


def small_angle_quat(dtheta):
    angle = float(np.linalg.norm(dtheta))
    if angle < 1e-12:
        return quat_normalize(np.array([1.0, 0.5 * dtheta[0], 0.5 * dtheta[1], 0.5 * dtheta[2]]))
    axis = dtheta / angle
    half = 0.5 * angle
    return np.array([math.cos(half), *(math.sin(half) * axis)], dtype=float)


def yaw_from_quat(q):
    w, x, y, z = q
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


class SimplifiedESKF15:
    def __init__(self, p0, v0):
        self.p = p0.astype(float).copy()
        self.v = v0.astype(float).copy()
        yaw0 = math.atan2(v0[0], v0[1]) if np.linalg.norm(v0[:2]) > 0.2 else 0.0
        self.q = np.array([math.cos(yaw0 / 2.0), 0.0, 0.0, math.sin(yaw0 / 2.0)], dtype=float)
        self.bg = np.zeros(3)
        self.ba = np.zeros(3)

        self.P = np.diag([
            25.0, 25.0, 100.0,          # position error variance
            4.0, 4.0, 9.0,              # velocity error variance
            deg2rad(8) ** 2, deg2rad(8) ** 2, deg2rad(20) ** 2,
            deg2rad(0.5) ** 2, deg2rad(0.5) ** 2, deg2rad(0.8) ** 2,
            0.08 ** 2, 0.08 ** 2, 0.12 ** 2,
        ])

        self.sigma_acc = 0.45
        self.sigma_gyro = deg2rad(1.5)
        self.sigma_ba_rw = 0.015
        self.sigma_bg_rw = deg2rad(0.08)
        self.last_innovation = np.zeros(3)
        self.last_innovation_norm = 0.0
        self.last_rejected = False

    def predict(self, dt):
        dt = max(0.02, min(float(dt), 5.0))

        # Nominal state. With no synchronized IMU samples, use zero acceleration
        # and constant velocity as the fallback inertial prediction.
        self.p = self.p + self.v * dt

        F = np.eye(15)
        F[0:3, 3:6] = np.eye(3) * dt
        F[3:6, 12:15] = -np.eye(3) * dt
        F[6:9, 9:12] = -np.eye(3) * dt

        Q = np.zeros((15, 15))
        Q[0:3, 0:3] = np.eye(3) * (0.02 ** 2) * dt
        Q[3:6, 3:6] = np.eye(3) * (self.sigma_acc ** 2) * dt
        Q[6:9, 6:9] = np.eye(3) * (self.sigma_gyro ** 2) * dt
        Q[9:12, 9:12] = np.eye(3) * (self.sigma_bg_rw ** 2) * dt
        Q[12:15, 12:15] = np.eye(3) * (self.sigma_ba_rw ** 2) * dt
        self.P = F @ self.P @ F.T + Q

    def update_gps_position(self, z, hdop):
        sigma_xy = max(2.5, min(25.0, 2.8 * hdop))
        sigma_z = max(8.0, min(40.0, 4.5 * hdop))
        R = np.diag([sigma_xy ** 2, sigma_xy ** 2, sigma_z ** 2])
        H = np.zeros((3, 15))
        H[0:3, 0:3] = np.eye(3)

        innovation = z - self.p
        innovation_norm = float(np.linalg.norm(innovation[:2]))
        self.last_innovation = innovation.copy()
        self.last_innovation_norm = innovation_norm
        self.last_rejected = False

        # Soft outlier gate. It rejects only very large GPS jumps, keeping real
        # walking turns and longer route segments.
        gate_m = max(45.0, 12.0 * sigma_xy)
        if innovation_norm > gate_m:
            self.last_rejected = True
            return False

        S = H @ self.P @ H.T + R
        K = self.P @ H.T @ np.linalg.inv(S)
        dx = K @ innovation

        self.p += dx[0:3]
        self.v += dx[3:6]
        self.q = quat_normalize(quat_mul(small_angle_quat(dx[6:9]), self.q))
        self.bg += dx[9:12]
        self.ba += dx[12:15]

        I = np.eye(15)
        KH = K @ H
        self.P = (I - KH) @ self.P @ (I - KH).T + K @ R @ K.T
        self.P = 0.5 * (self.P + self.P.T)
        return True


def nearest_distances_latlon(points, reference):
    ref_coords = [(p["lat"], p["lon"]) for p in reference]
    out = []
    for p in points:
        here = (p["lat"], p["lon"])
        out.append(min(haversine_m(here, q) for q in ref_coords))
    return out


def summarize_distances(label, distances):
    return {
        label + "_mean_m": statistics.fmean(distances) if distances else float("nan"),
        label + "_median_m": statistics.median(distances) if distances else float("nan"),
        label + "_p95_m": percentile(distances, 0.95),
        label + "_max_m": max(distances) if distances else float("nan"),
    }


def run_eskf(gps_points, frame):
    if len(gps_points) < 3:
        raise RuntimeError("Need at least 3 GPS points for ESKF")

    for p in gps_points:
        p["z_enu"] = frame.lla_to_enu(p["lat"], p["lon"], p["alt_m"])

    p0 = gps_points[0]["z_enu"]
    dt0 = max(1.0, gps_points[1]["t_s"] - gps_points[0]["t_s"])
    v0 = (gps_points[1]["z_enu"] - gps_points[0]["z_enu"]) / dt0
    eskf = SimplifiedESKF15(p0, v0)

    states = []
    last_t = gps_points[0]["t_s"]
    accepted = 0
    rejected = 0

    for index, point in enumerate(gps_points):
        dt = point["t_s"] - last_t if index > 0 else 0.0
        if index > 0:
            eskf.predict(dt)
        ok = eskf.update_gps_position(point["z_enu"], point["hdop"])
        if ok:
            accepted += 1
        else:
            rejected += 1
        last_t = point["t_s"]

        lat, lon, alt = frame.enu_to_lla(eskf.p)
        sigma_pos = np.sqrt(np.maximum(np.diag(eskf.P)[0:3], 0.0))
        states.append({
            "index": index,
            "t_s": point["t_s"],
            "source_file": point["source_file"],
            "gps_lat": point["lat"],
            "gps_lon": point["lon"],
            "gps_alt_m": point["alt_m"],
            "gps_e_m": point["z_enu"][0],
            "gps_n_m": point["z_enu"][1],
            "gps_u_m": point["z_enu"][2],
            "eskf_lat": lat,
            "eskf_lon": lon,
            "eskf_alt_m": alt,
            "eskf_e_m": eskf.p[0],
            "eskf_n_m": eskf.p[1],
            "eskf_u_m": eskf.p[2],
            "vel_e_mps": eskf.v[0],
            "vel_n_mps": eskf.v[1],
            "vel_u_mps": eskf.v[2],
            "yaw_deg": rad2deg(yaw_from_quat(eskf.q)),
            "sigma_e_m": sigma_pos[0],
            "sigma_n_m": sigma_pos[1],
            "sigma_u_m": sigma_pos[2],
            "innovation_xy_m": eskf.last_innovation_norm,
            "gps_update_accepted": 1 if ok else 0,
            "satellites": point["satellites"],
            "hdop": point["hdop"],
            "p_enu": eskf.p.copy(),
            "lat": lat,
            "lon": lon,
        })

    return states, accepted, rejected


def write_states(path, states):
    headers = [
        "index", "t_s", "source_file",
        "gps_lat", "gps_lon", "gps_alt_m", "gps_e_m", "gps_n_m", "gps_u_m",
        "eskf_lat", "eskf_lon", "eskf_alt_m", "eskf_e_m", "eskf_n_m", "eskf_u_m",
        "vel_e_mps", "vel_n_mps", "vel_u_mps", "yaw_deg",
        "sigma_e_m", "sigma_n_m", "sigma_u_m", "innovation_xy_m",
        "gps_update_accepted", "satellites", "hdop",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in states:
            writer.writerow({h: row.get(h, "") for h in headers})


def write_summary(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["item", "value", "unit", "note"])
        for item, value, unit, note in rows:
            writer.writerow([item, value, unit, note])


def make_track_overlay(phone, gps_quality, states):
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    plt.rcParams["font.sans-serif"] = ["DejaVu Sans", "Arial"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, ax = plt.subplots(figsize=(8.2, 6.4))
    ax.plot([p["lon"] for p in phone], [p["lat"] for p in phone],
            color="#16a34a", linewidth=2.4, label="Phone GNSS reference")
    ax.plot([p["lon"] for p in gps_quality], [p["lat"] for p in gps_quality],
            color="#60a5fa", linewidth=1.0, alpha=0.65, label="ESP32 GPS filtered")
    ax.plot([p["eskf_lon"] for p in states], [p["eskf_lat"] for p in states],
            color="#ef4444", linewidth=1.8, label="15D simplified ESKF")
    ax.scatter(phone[0]["lon"], phone[0]["lat"], color="#15803d", s=48, label="Start")
    ax.scatter(phone[-1]["lon"], phone[-1]["lat"], color="#7f1d1d", s=48, marker="x", label="End")
    ax.set_title("Offline 15D simplified ESKF trajectory")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="best")
    fig.tight_layout()
    out = FIG_DIR / ("eskf_15d_track_overlay_%s.png" % TAG)
    fig.savefig(out, dpi=180)
    plt.close(fig)
    return out


def make_error_compare(gps_dist, eskf_dist):
    fig, ax = plt.subplots(figsize=(8.0, 5.2))
    labels = ["Mean", "Median", "P95"]
    gps_vals = [statistics.fmean(gps_dist), statistics.median(gps_dist), percentile(gps_dist, 0.95)]
    eskf_vals = [statistics.fmean(eskf_dist), statistics.median(eskf_dist), percentile(eskf_dist, 0.95)]
    x = np.arange(len(labels))
    width = 0.35
    ax.bar(x - width / 2, gps_vals, width, color="#60a5fa", label="GPS filtered")
    ax.bar(x + width / 2, eskf_vals, width, color="#ef4444", label="15D simplified ESKF")
    ax.set_xticks(x, labels)
    ax.set_ylabel("Nearest distance to phone reference (m)")
    ax.set_title("GPS vs ESKF trajectory error")
    ax.grid(True, axis="y", alpha=0.25)
    ax.legend()
    fig.tight_layout()
    out = FIG_DIR / ("eskf_15d_error_compare_%s.png" % TAG)
    fig.savefig(out, dpi=180)
    plt.close(fig)
    return out


def make_innovation_plot(states):
    t = [s["t_s"] - states[0]["t_s"] for s in states]
    innovation = [s["innovation_xy_m"] for s in states]
    sigma_e = [s["sigma_e_m"] for s in states]
    sigma_n = [s["sigma_n_m"] for s in states]
    fig, axes = plt.subplots(2, 1, figsize=(9, 6.4), sharex=True)
    axes[0].plot(t, innovation, color="#f97316")
    axes[0].set_ylabel("GPS innovation XY (m)")
    axes[0].grid(True, alpha=0.25)
    axes[1].plot(t, sigma_e, label="sigma east", color="#2563eb")
    axes[1].plot(t, sigma_n, label="sigma north", color="#16a34a")
    axes[1].set_ylabel("Position sigma (m)")
    axes[1].set_xlabel("Time (s)")
    axes[1].grid(True, alpha=0.25)
    axes[1].legend()
    axes[0].set_title("15D simplified ESKF innovation and covariance")
    fig.tight_layout()
    out = FIG_DIR / ("eskf_15d_innovation_%s.png" % TAG)
    fig.savefig(out, dpi=180)
    plt.close(fig)
    return out


def make_folium_map(phone, gps_quality, states):
    import folium

    center = [
        statistics.fmean([p["lat"] for p in phone]),
        statistics.fmean([p["lon"] for p in phone]),
    ]
    fmap = folium.Map(location=center, zoom_start=17, tiles="OpenStreetMap")
    folium.PolyLine([(p["lat"], p["lon"]) for p in phone],
                    color="green", weight=5, opacity=0.9, tooltip="Phone GNSS reference").add_to(fmap)
    folium.PolyLine([(p["lat"], p["lon"]) for p in gps_quality],
                    color="blue", weight=3, opacity=0.45, tooltip="ESP32 GPS filtered").add_to(fmap)
    folium.PolyLine([(p["eskf_lat"], p["eskf_lon"]) for p in states],
                    color="red", weight=4, opacity=0.85, tooltip="15D simplified ESKF").add_to(fmap)
    folium.LayerControl().add_to(fmap)
    out = FIG_DIR / ("eskf_15d_track_overlay_%s.html" % TAG)
    fmap.save(str(out))
    return out


def main():
    gps_file = latest_gps_points_file()
    gps_all = read_gps_points(gps_file)
    phone = read_phone_reference()
    gps_quality = [
        p for p in gps_all
        if p["satellites"] >= QUALITY_MIN_SATS and p["hdop"] <= QUALITY_MAX_HDOP
    ]
    if len(gps_quality) < 3:
        raise RuntimeError("Not enough quality-filtered GPS points")

    lat0 = phone[0]["lat"] if phone else gps_quality[0]["lat"]
    lon0 = phone[0]["lon"] if phone else gps_quality[0]["lon"]
    alt0_values = [p["alt_m"] for p in gps_quality[:20] if not math.isnan(p["alt_m"])]
    alt0 = statistics.fmean(alt0_values) if alt0_values else 0.0
    frame = LocalFrame(lat0, lon0, alt0)

    states, accepted, rejected = run_eskf(gps_quality, frame)

    state_path = ANALYSIS_DIR / ("eskf_15d_offline_states_%s.csv" % TAG)
    summary_path = ANALYSIS_DIR / ("eskf_15d_offline_summary_%s.csv" % TAG)
    write_states(state_path, states)

    gps_dist = nearest_distances_latlon(gps_quality, phone)
    eskf_dist = nearest_distances_latlon(states, phone)
    gps_match30 = [d for d in gps_dist if d <= 30.0]
    eskf_match30 = [d for d in eskf_dist if d <= 30.0]

    gps_summary = summarize_distances("gps_filtered_to_phone", gps_dist)
    eskf_summary = summarize_distances("eskf_to_phone", eskf_dist)
    rows = [
        ("model", "offline_15d_simplified_eskf", "", ""),
        ("state_dimension", 15, "dim", "dx=[dp,dv,dtheta,dbg,dba]"),
        ("nominal_state", "p(3), v(3), q(4), bg(3), ba(3)", "", ""),
        ("input_mode", "gps_only_fallback", "", "no synchronized IMU in current outdoor dataset"),
        ("gps_points_source", str(gps_file), "", ""),
        ("phone_reference_source", str(ANALYSIS_DIR / ("gps_phone_reference_points_%s.csv" % TAG)), "", ""),
        ("gps_quality_filter", "satellites>=4 and HDOP<=5", "", ""),
        ("gps_quality_points", len(gps_quality), "points", ""),
        ("eskf_states", len(states), "states", ""),
        ("gps_updates_accepted", accepted, "updates", ""),
        ("gps_updates_rejected", rejected, "updates", "large innovation gate"),
        ("gps_filtered_distance", path_distance_latlon(gps_quality), "m", ""),
        ("eskf_distance", path_distance_latlon(states), "m", ""),
        ("gps_matched30_points", len(gps_match30), "points", "nearest distance <= 30 m"),
        ("eskf_matched30_points", len(eskf_match30), "points", "nearest distance <= 30 m"),
        ("gps_matched30_median", statistics.median(gps_match30), "m", ""),
        ("eskf_matched30_median", statistics.median(eskf_match30), "m", ""),
        ("gps_matched30_p95", percentile(gps_match30, 0.95), "m", ""),
        ("eskf_matched30_p95", percentile(eskf_match30, 0.95), "m", ""),
    ]
    for key, value in gps_summary.items():
        rows.append((key, value, "m", "nearest distance to phone reference"))
    for key, value in eskf_summary.items():
        rows.append((key, value, "m", "nearest distance to phone reference"))
    rows.extend([
        ("mean_innovation_xy", statistics.fmean([s["innovation_xy_m"] for s in states]), "m", ""),
        ("median_innovation_xy", statistics.median([s["innovation_xy_m"] for s in states]), "m", ""),
        ("final_sigma_e", states[-1]["sigma_e_m"], "m", ""),
        ("final_sigma_n", states[-1]["sigma_n_m"], "m", ""),
        ("final_sigma_u", states[-1]["sigma_u_m"], "m", ""),
    ])
    write_summary(summary_path, rows)

    track_png = make_track_overlay(phone, gps_quality, states)
    error_png = make_error_compare(gps_dist, eskf_dist)
    innovation_png = make_innovation_plot(states)
    html_map = make_folium_map(phone, gps_quality, states)

    print("GPS source:", gps_file)
    print("Phone reference points:", len(phone))
    print("GPS quality points:", len(gps_quality))
    print("ESKF states:", len(states))
    print("GPS updates accepted/rejected:", accepted, rejected)
    print("GPS filtered median/P95 to phone: %.3f / %.3f m" % (
        statistics.median(gps_dist), percentile(gps_dist, 0.95)))
    print("ESKF median/P95 to phone: %.3f / %.3f m" % (
        statistics.median(eskf_dist), percentile(eskf_dist, 0.95)))
    print("GPS matched30 median/P95: %.3f / %.3f m" % (
        statistics.median(gps_match30), percentile(gps_match30, 0.95)))
    print("ESKF matched30 median/P95: %.3f / %.3f m" % (
        statistics.median(eskf_match30), percentile(eskf_match30, 0.95)))
    print("Wrote:", state_path)
    print("Wrote:", summary_path)
    print("Figure:", track_png)
    print("Figure:", error_png)
    print("Figure:", innovation_png)
    print("Map:", html_map)


if __name__ == "__main__":
    main()
