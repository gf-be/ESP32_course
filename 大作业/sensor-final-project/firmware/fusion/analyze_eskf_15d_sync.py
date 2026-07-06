# -*- coding: utf-8 -*-
"""
Offline 15D ESKF for synchronized IMU + GPS logs.

Input:
  data/fusion_comparison/imu_gps_sync/imu_gps_sync_*.csv

State:
  nominal x = [p(3), v(3), q(4), bg(3), ba(3)]
  error dx  = [dp(3), dv(3), dtheta(3), dbg(3), dba(3)]^T

Updates:
  - IMU prediction at log sample rate
  - GPS position update when gps_updated=1 and gps_usable=1
  - GPS horizontal velocity update when speed/course are available
"""

from pathlib import Path
import csv
import math
import statistics

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


EARTH_R = 6378137.0
G = 9.80665

ACC_C = np.array([
    [0.9936363144, 0.0798200426, 0.0766064259],
    [-0.0698260446, 0.9977966301, 0.0003414386],
    [-0.0536159808, 0.0015940015, 0.9789750285],
])
ACC_D = np.array([-0.0114873061, -0.0080361168, -0.0045358955])
GYRO_BIAS_DPS = np.array([0.228303741, 0.964654373, -0.100939275])
MAG_BIAS = np.array([77.082135, -94.427834, -36.852085])
MAG_MATRIX = np.array([
    [1.0102826701, 0.0065974430, -0.0096782755],
    [0.0065974430, 0.9756936862, -0.0109598281],
    [-0.0096782755, -0.0109598281, 1.0154785728],
])


def project_root():
    return Path(__file__).resolve().parents[2]


ROOT = project_root()
SYNC_DIR = ROOT / "data" / "fusion_comparison" / "imu_gps_sync"
ANALYSIS_DIR = ROOT / "data" / "analysis"
FIG_DIR = ROOT / "data" / "figures"


def latest_file(folder, pattern):
    files = sorted(folder.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


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


def read_sync_csv(path):
    rows = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(line for line in f if not line.startswith("#") and line.strip())
        for row in reader:
            rows.append({
                "t_ms": to_float(row.get("t_ms")),
                "acc_raw": np.array([
                    to_float(row.get("ax_g")),
                    to_float(row.get("ay_g")),
                    to_float(row.get("az_g")),
                ], dtype=float),
                "gyro_raw_dps": np.array([
                    to_float(row.get("gx_dps")),
                    to_float(row.get("gy_dps")),
                    to_float(row.get("gz_dps")),
                ], dtype=float),
                "mag_raw": np.array([
                    to_float(row.get("mx_raw")),
                    to_float(row.get("my_raw")),
                    to_float(row.get("mz_raw")),
                ], dtype=float),
                "gps_updated": to_int(row.get("gps_updated")),
                "gps_valid": to_int(row.get("gps_valid")),
                "gps_usable": to_int(row.get("gps_usable")),
                "fix_quality": to_int(row.get("fix_quality")),
                "satellites": to_int(row.get("satellites")),
                "hdop": to_float(row.get("hdop"), 99.0),
                "lat": to_float(row.get("gps_lat")),
                "lon": to_float(row.get("gps_lon")),
                "alt_m": to_float(row.get("gps_alt_m"), 0.0),
                "speed_mps": to_float(row.get("gps_speed_mps")),
                "course_deg": to_float(row.get("gps_course_deg")),
                "nmea_count": to_int(row.get("nmea_count")),
                "fix_count": to_int(row.get("fix_count")),
            })
    rows = [r for r in rows if math.isfinite(r["t_ms"])]
    rows.sort(key=lambda r: r["t_ms"])
    return rows


def normalize(v):
    n = float(np.linalg.norm(v))
    if n < 1e-12:
        return v.copy()
    return v / n


def skew(v):
    x, y, z = v
    return np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]], dtype=float)


def quat_normalize(q):
    return normalize(q) if np.linalg.norm(q) > 1e-12 else np.array([1.0, 0.0, 0.0, 0.0])


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


def quat_to_rot(q):
    q0, q1, q2, q3 = q
    return np.array([
        [1 - 2 * (q2 * q2 + q3 * q3), 2 * (q1 * q2 - q0 * q3), 2 * (q1 * q3 + q0 * q2)],
        [2 * (q1 * q2 + q0 * q3), 1 - 2 * (q1 * q1 + q3 * q3), 2 * (q2 * q3 - q0 * q1)],
        [2 * (q1 * q3 - q0 * q2), 2 * (q2 * q3 + q0 * q1), 1 - 2 * (q1 * q1 + q2 * q2)],
    ], dtype=float)


def euler_from_quat(q):
    q0, q1, q2, q3 = q
    roll = math.atan2(2 * (q0 * q1 + q2 * q3), 1 - 2 * (q1 * q1 + q2 * q2))
    s = max(-1.0, min(1.0, 2 * (q0 * q2 - q3 * q1)))
    pitch = math.asin(s)
    yaw = math.atan2(2 * (q0 * q3 + q1 * q2), 1 - 2 * (q2 * q2 + q3 * q3))
    return math.degrees(roll), math.degrees(pitch), math.degrees(yaw)


def quat_from_euler(roll_deg, pitch_deg, yaw_deg):
    cr = math.cos(math.radians(roll_deg) / 2)
    sr = math.sin(math.radians(roll_deg) / 2)
    cp = math.cos(math.radians(pitch_deg) / 2)
    sp = math.sin(math.radians(pitch_deg) / 2)
    cy = math.cos(math.radians(yaw_deg) / 2)
    sy = math.sin(math.radians(yaw_deg) / 2)
    return quat_normalize(np.array([
        cr * cp * cy + sr * sp * sy,
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
    ], dtype=float))


def accel_angles(acc):
    ax, ay, az = acc
    roll = math.degrees(math.atan2(ay, az))
    pitch = math.degrees(math.atan2(-ax, math.sqrt(ay * ay + az * az)))
    return roll, pitch


def mag_yaw(mag, roll_deg, pitch_deg):
    mx, my, mz = mag
    roll = math.radians(roll_deg)
    pitch = math.radians(pitch_deg)
    mx2 = mx * math.cos(pitch) + mz * math.sin(pitch)
    my2 = mx * math.sin(roll) * math.sin(pitch) + my * math.cos(roll) - mz * math.sin(roll) * math.cos(pitch)
    return math.degrees(math.atan2(-my2, mx2))


def calibrate(row):
    acc = ACC_C @ row["acc_raw"] + ACC_D
    gyro = row["gyro_raw_dps"] - GYRO_BIAS_DPS
    mag = MAG_MATRIX @ (row["mag_raw"] - MAG_BIAS)
    return acc, gyro, mag


class LocalFrame:
    def __init__(self, lat0, lon0, alt0=0.0):
        self.lat0 = lat0
        self.lon0 = lon0
        self.alt0 = alt0
        self.cos_lat0 = math.cos(math.radians(lat0))

    def lla_to_enu(self, lat, lon, alt=0.0):
        east = math.radians(lon - self.lon0) * EARTH_R * self.cos_lat0
        north = math.radians(lat - self.lat0) * EARTH_R
        up = alt - self.alt0
        return np.array([east, north, up], dtype=float)

    def enu_to_lla(self, p):
        lat = self.lat0 + math.degrees(p[1] / EARTH_R)
        lon = self.lon0 + math.degrees(p[0] / (EARTH_R * self.cos_lat0))
        alt = self.alt0 + p[2]
        return lat, lon, alt


def gps_velocity_enu(speed_mps, course_deg):
    if not (math.isfinite(speed_mps) and math.isfinite(course_deg)):
        return None
    course = math.radians(course_deg)
    return np.array([speed_mps * math.sin(course), speed_mps * math.cos(course), 0.0], dtype=float)


def haversine_m(lat1, lon1, lat2, lon2):
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2.0 * EARTH_R * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))


class ESKF15:
    def __init__(self, p0, q0, q_scale=1.0):
        self.p = p0.copy()
        self.v = np.zeros(3)
        self.q = q0.copy()
        self.q_scale = max(1e-6, float(q_scale))
        self.bg = np.zeros(3)  # rad/s residual bias
        self.ba = np.zeros(3)  # m/s^2 residual bias
        self.P = np.diag([
            25.0, 25.0, 100.0,
            4.0, 4.0, 9.0,
            math.radians(8) ** 2, math.radians(8) ** 2, math.radians(20) ** 2,
            math.radians(0.5) ** 2, math.radians(0.5) ** 2, math.radians(0.8) ** 2,
            0.08 ** 2, 0.08 ** 2, 0.12 ** 2,
        ])
        self.last_pos_innov = np.zeros(3)
        self.last_vel_innov = np.zeros(3)
        self.pos_updates = 0
        self.vel_updates = 0
        self.rejects = 0

    def predict(self, dt, acc_g, gyro_dps):
        dt = max(0.001, min(float(dt), 0.2))
        omega = np.radians(gyro_dps) - self.bg
        self.q = quat_normalize(quat_mul(self.q, small_angle_quat(omega * dt)))

        r_bn = quat_to_rot(self.q)
        f_body = acc_g * G
        a_nav = r_bn @ f_body - np.array([0.0, 0.0, G]) - self.ba
        a_norm = float(np.linalg.norm(a_nav))
        if a_norm > 20.0:
            a_nav *= 20.0 / a_norm

        self.p += self.v * dt + 0.5 * a_nav * dt * dt
        self.v += a_nav * dt

        F = np.eye(15)
        F[0:3, 3:6] = np.eye(3) * dt
        F[3:6, 6:9] = -r_bn @ skew(f_body) * dt
        F[3:6, 12:15] = -np.eye(3) * dt
        F[6:9, 9:12] = -np.eye(3) * dt

        Q = np.zeros((15, 15))
        Q[0:3, 0:3] = np.eye(3) * (0.02 ** 2) * dt
        Q[3:6, 3:6] = np.eye(3) * (0.60 ** 2) * dt
        Q[6:9, 6:9] = np.eye(3) * (math.radians(1.2) ** 2) * dt
        Q[9:12, 9:12] = np.eye(3) * (math.radians(0.08) ** 2) * dt
        Q[12:15, 12:15] = np.eye(3) * (0.015 ** 2) * dt
        Q *= self.q_scale
        self.P = F @ self.P @ F.T + Q
        self.P = 0.5 * (self.P + self.P.T)

    def inject(self, dx):
        self.p += dx[0:3]
        self.v += dx[3:6]
        self.q = quat_normalize(quat_mul(small_angle_quat(dx[6:9]), self.q))
        self.bg += dx[9:12]
        self.ba += dx[12:15]

    def update_linear(self, innovation, h, r_diag):
        H = np.zeros((len(innovation), 15))
        for row, state_index in enumerate(h):
            H[row, state_index] = 1.0
        R = np.diag(r_diag)
        S = H @ self.P @ H.T + R
        K = self.P @ H.T @ np.linalg.inv(S)
        dx = K @ innovation
        self.inject(dx)
        I = np.eye(15)
        KH = K @ H
        self.P = (I - KH) @ self.P @ (I - KH).T + K @ R @ K.T
        self.P = 0.5 * (self.P + self.P.T)

    def update_gps_position(self, z, hdop):
        innov = z - self.p
        self.last_pos_innov = innov.copy()
        sigma_xy = max(2.5, min(25.0, 2.8 * hdop))
        sigma_z = max(8.0, min(45.0, 4.5 * hdop))
        gate = max(45.0, 12.0 * sigma_xy)
        if float(np.linalg.norm(innov[:2])) > gate:
            self.rejects += 1
            return False
        self.update_linear(innov, [0, 1, 2], [sigma_xy ** 2, sigma_xy ** 2, sigma_z ** 2])
        self.pos_updates += 1
        return True

    def update_gps_velocity(self, z_vel, hdop):
        innov = z_vel - self.v
        self.last_vel_innov = innov.copy()
        sigma_v = max(0.35, min(3.0, 0.20 + 0.18 * hdop))
        self.update_linear(innov[:2], [3, 4], [sigma_v ** 2, sigma_v ** 2])
        self.vel_updates += 1
        return True


def initial_quat(row):
    acc, _, mag = calibrate(row)
    r, p = accel_angles(normalize(acc))
    y = mag_yaw(normalize(mag), r, p)
    return quat_from_euler(r, p, y)


def valid_gps(row):
    return row["gps_usable"] == 1 and math.isfinite(row["lat"]) and math.isfinite(row["lon"]) and abs(row["lat"]) > 1e-9


def run_eskf(rows, q_scale=1.0):
    first = next((r for r in rows if valid_gps(r)), None)
    if first is None:
        raise RuntimeError("No usable GPS fix found in synchronized log")

    frame = LocalFrame(first["lat"], first["lon"], first["alt_m"])
    eskf = ESKF15(frame.lla_to_enu(first["lat"], first["lon"], first["alt_m"]), initial_quat(first), q_scale=q_scale)
    states = []
    last_t = first["t_ms"] / 1000.0
    initialized = False

    for row in rows:
        t = row["t_ms"] / 1000.0
        if row is first:
            initialized = True
            last_t = t
        if not initialized:
            continue

        dt = t - last_t
        last_t = t
        acc, gyro, _ = calibrate(row)
        eskf.predict(dt, acc, gyro)

        if row["gps_updated"] and valid_gps(row):
            z = frame.lla_to_enu(row["lat"], row["lon"], row["alt_m"])
            if eskf.update_gps_position(z, row["hdop"]):
                vgps = gps_velocity_enu(row["speed_mps"], row["course_deg"])
                if vgps is not None and np.linalg.norm(vgps[:2]) > 0.05:
                    eskf.update_gps_velocity(vgps, row["hdop"])

        lat, lon, alt = frame.enu_to_lla(eskf.p)
        roll, pitch, yaw = euler_from_quat(eskf.q)
        sig = np.sqrt(np.maximum(np.diag(eskf.P)[0:6], 0.0))
        states.append({
            "t_s": t - first["t_ms"] / 1000.0,
            "gps_updated": row["gps_updated"],
            "gps_usable": row["gps_usable"],
            "gps_lat": row["lat"],
            "gps_lon": row["lon"],
            "gps_alt_m": row["alt_m"],
            "est_lat": lat,
            "est_lon": lon,
            "est_alt_m": alt,
            "e_m": eskf.p[0],
            "n_m": eskf.p[1],
            "u_m": eskf.p[2],
            "ve_mps": eskf.v[0],
            "vn_mps": eskf.v[1],
            "vu_mps": eskf.v[2],
            "roll_deg": roll,
            "pitch_deg": pitch,
            "yaw_deg": yaw,
            "pos_innov_xy_m": float(np.linalg.norm(eskf.last_pos_innov[:2])),
            "vel_innov_xy_m": float(np.linalg.norm(eskf.last_vel_innov[:2])),
            "sigma_e_m": sig[0],
            "sigma_n_m": sig[1],
            "sigma_u_m": sig[2],
            "sigma_ve_mps": sig[3],
            "sigma_vn_mps": sig[4],
            "sigma_vu_mps": sig[5],
            "pos_updates": eskf.pos_updates,
            "vel_updates": eskf.vel_updates,
            "rejects": eskf.rejects,
            "satellites": row["satellites"],
            "hdop": row["hdop"],
        })
    return states, eskf


def path_distance_xy(rows, x_key, y_key):
    total = 0.0
    prev = None
    for row in rows:
        x = row.get(x_key)
        y = row.get(y_key)
        if not (math.isfinite(x) and math.isfinite(y)):
            continue
        if prev is not None:
            total += math.hypot(x - prev[0], y - prev[1])
        prev = (x, y)
    return total


def path_distance_latlon(rows, lat_key, lon_key):
    total = 0.0
    prev = None
    for row in rows:
        lat = row.get(lat_key)
        lon = row.get(lon_key)
        if not (math.isfinite(lat) and math.isfinite(lon) and abs(lat) > 1e-9):
            continue
        if prev is not None:
            total += haversine_m(prev[0], prev[1], lat, lon)
        prev = (lat, lon)
    return total


def finite_values(rows, key):
    return [row[key] for row in rows if math.isfinite(row.get(key, float("nan")))]


def pct(values, q):
    vals = sorted(v for v in values if math.isfinite(v))
    if not vals:
        return float("nan")
    idx = int(math.ceil(q * len(vals))) - 1
    return vals[max(0, min(idx, len(vals) - 1))]


def write_states(path, states):
    keys = [
        "t_s", "gps_updated", "gps_usable", "gps_lat", "gps_lon", "gps_alt_m",
        "est_lat", "est_lon", "est_alt_m", "e_m", "n_m", "u_m",
        "ve_mps", "vn_mps", "vu_mps", "roll_deg", "pitch_deg", "yaw_deg",
        "pos_innov_xy_m", "vel_innov_xy_m", "sigma_e_m", "sigma_n_m", "sigma_u_m",
        "sigma_ve_mps", "sigma_vn_mps", "sigma_vu_mps", "pos_updates", "vel_updates",
        "rejects", "satellites", "hdop",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        for row in states:
            writer.writerow({k: row.get(k, "") for k in keys})


def write_summary(path, items):
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["item", "value", "unit", "note"])
        for row in items:
            writer.writerow(row)


def plot_track(path, states):
    gps = [s for s in states if s["gps_usable"] == 1 and math.isfinite(s["gps_lat"]) and abs(s["gps_lat"]) > 1e-9]
    fig, ax = plt.subplots(figsize=(8, 7))
    if gps:
        ax.plot([g["gps_lon"] for g in gps], [g["gps_lat"] for g in gps], label="GPS measurement", linewidth=1.2, alpha=0.7)
    ax.plot([s["est_lon"] for s in states], [s["est_lat"] for s in states], label="15D ESKF estimate", linewidth=1.8)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title("Synchronized IMU+GPS 15D ESKF trajectory")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def plot_innovation(path, states):
    t = [s["t_s"] for s in states]
    fig, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True)
    axes[0].plot(t, [s["pos_innov_xy_m"] for s in states], label="position innovation XY")
    axes[0].set_ylabel("m")
    axes[0].grid(True, alpha=0.3)
    axes[0].legend()
    axes[1].plot(t, [s["vel_innov_xy_m"] for s in states], label="velocity innovation XY", color="tab:orange")
    axes[1].set_ylabel("m/s")
    axes[1].grid(True, alpha=0.3)
    axes[1].legend()
    axes[2].plot(t, [s["sigma_e_m"] for s in states], label="sigma east")
    axes[2].plot(t, [s["sigma_n_m"] for s in states], label="sigma north")
    axes[2].set_xlabel("Time / s")
    axes[2].set_ylabel("m")
    axes[2].grid(True, alpha=0.3)
    axes[2].legend()
    fig.suptitle("Synchronized IMU+GPS ESKF innovation and covariance")
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def main():
    src = latest_file(SYNC_DIR, "imu_gps_sync_*.csv")
    if src is None:
        raise SystemExit("No imu_gps_sync_*.csv found in %s" % SYNC_DIR)

    rows = read_sync_csv(src)
    states, eskf = run_eskf(rows)
    stamp = src.stem.replace("imu_gps_sync_", "")
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    states_path = ANALYSIS_DIR / ("eskf_15d_sync_states_%s.csv" % stamp)
    summary_path = ANALYSIS_DIR / ("eskf_15d_sync_summary_%s.csv" % stamp)
    track_path = FIG_DIR / ("eskf_15d_sync_track_%s.png" % stamp)
    innovation_path = FIG_DIR / ("eskf_15d_sync_innovation_%s.png" % stamp)

    write_states(states_path, states)
    plot_track(track_path, states)
    plot_innovation(innovation_path, states)

    pos_innov = finite_values(states, "pos_innov_xy_m")
    vel_innov = finite_values(states, "vel_innov_xy_m")
    gps_rows = [s for s in states if s["gps_usable"] == 1 and math.isfinite(s["gps_lat"]) and abs(s["gps_lat"]) > 1e-9]
    duration = states[-1]["t_s"] - states[0]["t_s"] if len(states) >= 2 else 0.0
    sample_rate = len(rows) / ((rows[-1]["t_ms"] - rows[0]["t_ms"]) / 1000.0) if len(rows) >= 2 else float("nan")
    summary = [
        ("source_csv", str(src), "", "synchronized IMU+GPS log"),
        ("rows", len(rows), "rows", ""),
        ("eskf_states", len(states), "states", ""),
        ("duration", duration, "s", ""),
        ("sample_rate", sample_rate, "Hz", "from t_ms"),
        ("gps_usable_rows", len(gps_rows), "rows", ""),
        ("pos_updates", eskf.pos_updates, "updates", "GPS position updates accepted"),
        ("vel_updates", eskf.vel_updates, "updates", "GPS velocity updates accepted"),
        ("gps_rejects", eskf.rejects, "updates", "position innovation gate rejects"),
        ("gps_measurement_distance", path_distance_latlon(gps_rows, "gps_lat", "gps_lon"), "m", "GPS measurement horizontal path length"),
        ("eskf_latlon_distance", path_distance_latlon(states, "est_lat", "est_lon"), "m", "ESKF estimated lat/lon path length"),
        ("eskf_enu_distance", path_distance_xy(states, "e_m", "n_m"), "m", "ESKF ENU horizontal path length"),
        ("pos_innovation_median", statistics.median(pos_innov) if pos_innov else float("nan"), "m", ""),
        ("pos_innovation_p95", pct(pos_innov, 0.95), "m", ""),
        ("vel_innovation_median", statistics.median(vel_innov) if vel_innov else float("nan"), "m/s", ""),
        ("vel_innovation_p95", pct(vel_innov, 0.95), "m/s", ""),
        ("final_sigma_e", states[-1]["sigma_e_m"], "m", ""),
        ("final_sigma_n", states[-1]["sigma_n_m"], "m", ""),
        ("final_sigma_ve", states[-1]["sigma_ve_mps"], "m/s", ""),
        ("final_sigma_vn", states[-1]["sigma_vn_mps"], "m/s", ""),
    ]
    write_summary(summary_path, summary)

    print("Analyzed:", src)
    print("Rows:", len(rows), "states:", len(states))
    print("Position updates:", eskf.pos_updates, "velocity updates:", eskf.vel_updates, "rejects:", eskf.rejects)
    print("Sample rate: %.3f Hz" % sample_rate)
    print("Position innovation median/P95: %.3f / %.3f m" % (
        statistics.median(pos_innov) if pos_innov else float("nan"),
        pct(pos_innov, 0.95),
    ))
    print("Wrote:", states_path)
    print("Wrote:", summary_path)
    print("Figure:", track_path)
    print("Figure:", innovation_path)


if __name__ == "__main__":
    main()
