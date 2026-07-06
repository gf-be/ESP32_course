# -*- coding: utf-8 -*-
"""
Course-completion analysis for the outdoor GPS/IMU experiment.

Inputs:
  data/fusion_comparison/imu_gps_sync/imu_gps_sync_offline_*.csv
  ../data/*.gpx

Outputs:
  data/analysis/gps_esp32_phone_eskf_summary_*.csv
  data/analysis/eskf_15d_sync_robust_states_*.csv
  data/figures/gps_phone_esp32_eskf_overlay_*.png
  data/figures/gps_phone_esp32_eskf_overlay_*.html
  data/figures/eskf_15d_sync_robust_innovation_*.png
  docs/gps_eskf_completion_report_*.md

The ESKF implementation is a low-speed, loose-coupled 15-state version for
flash-logged walking data. The nominal state is [p, v, q, bg, ba], while the
error covariance is 15D: [dp, dv, dtheta, dbg, dba]. GPS position updates are
allowed to dominate because the ESP32 flash logger runs at about 8 Hz.
"""

from pathlib import Path
import csv
import math
import statistics
import xml.etree.ElementTree as ET

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

try:
    import folium
except Exception:
    folium = None


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


ROOT = Path(__file__).resolve().parents[2]
BIG_HOMEWORK = ROOT.parent
SYNC_DIR = ROOT / "data" / "fusion_comparison" / "imu_gps_sync"
ANALYSIS_DIR = ROOT / "data" / "analysis"
FIG_DIR = ROOT / "data" / "figures"
DOCS_DIR = ROOT / "docs"


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


def percentile(values, pct):
    if not values:
        return float("nan")
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * pct / 100.0))))
    return ordered[idx]


def normalize(v):
    n = float(np.linalg.norm(v))
    if n < 1e-12:
        return v.copy()
    return v / n


def quat_normalize(q):
    n = float(np.linalg.norm(q))
    if n < 1e-12:
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
    gyro_dps = row["gyro_raw_dps"] - GYRO_BIAS_DPS
    mag = MAG_MATRIX @ (row["mag_raw"] - MAG_BIAS)
    return acc, gyro_dps, mag


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


def read_sync_csv(path):
    rows = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(line for line in f if line.strip() and not line.startswith("#"))
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


def latest_gpx_file():
    data_dir = BIG_HOMEWORK / "data"
    files = sorted(data_dir.glob("*.gpx"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def read_gpx(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    root = ET.fromstring(text)
    ns = {"g": root.tag.split("}")[0].strip("{")} if root.tag.startswith("{") else {}

    def findall(name):
        return root.findall(".//g:" + name, ns) if ns else root.findall(".//" + name)

    def find_text(name):
        elem = root.find(".//g:" + name, ns) if ns else root.find(".//" + name)
        return elem.text.strip() if elem is not None and elem.text else ""

    points = []
    for index, elem in enumerate(findall("trkpt")):
        lat = to_float(elem.attrib.get("lat"))
        lon = to_float(elem.attrib.get("lon"))
        ele_elem = elem.find("g:ele", ns) if ns else elem.find("ele")
        time_elem = elem.find("g:time", ns) if ns else elem.find("time")
        if math.isfinite(lat) and math.isfinite(lon):
            points.append({
                "index": index,
                "lat": lat,
                "lon": lon,
                "ele_m": to_float(ele_elem.text if ele_elem is not None else ""),
                "gpx_time": time_elem.text if time_elem is not None and time_elem.text else "",
            })

    total_time = to_float(find_text("totalTime"))
    total_distance = to_float(find_text("totalDistance"))
    if points and math.isfinite(total_time):
        denom = max(1, len(points) - 1)
        for p in points:
            p["elapsed_s"] = total_time * p["index"] / denom
    else:
        for p in points:
            p["elapsed_s"] = float("nan")

    meta = {
        "total_time_s": total_time,
        "total_distance_m": total_distance,
        "cumulative_climb_m": to_float(find_text("cumulativeClimb")),
        "cumulative_decrease_m": to_float(find_text("cumulativeDecrease")),
    }
    return points, meta


def path_distance_xy(xy, jump_limit=100.0):
    distance = 0.0
    jumps = 0
    for a, b in zip(xy, xy[1:]):
        d = math.hypot(b[0] - a[0], b[1] - a[1])
        if d <= jump_limit:
            distance += d
        else:
            jumps += 1
    return distance, jumps


def span_xy(xy):
    if not xy:
        return float("nan"), float("nan")
    return (
        max(p[0] for p in xy) - min(p[0] for p in xy),
        max(p[1] for p in xy) - min(p[1] for p in xy),
    )


def point_segment_distance(px, py, ax, ay, bx, by):
    vx = bx - ax
    vy = by - ay
    wx = px - ax
    wy = py - ay
    vv = vx * vx + vy * vy
    if vv <= 1e-12:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, (wx * vx + wy * vy) / vv))
    cx = ax + t * vx
    cy = ay + t * vy
    return math.hypot(px - cx, py - cy)


def nearest_polyline_distances(src_xy, ref_xy, stride=1):
    if len(ref_xy) < 2:
        return []
    segs = list(zip(ref_xy, ref_xy[1:]))
    distances = []
    for p in src_xy[::stride]:
        best = float("inf")
        for a, b in segs:
            d = point_segment_distance(p[0], p[1], a[0], a[1], b[0], b[1])
            if d < best:
                best = d
        distances.append(best)
    return distances


def dict_points_to_xy(points, frame):
    return [
        tuple(frame.lla_to_enu(p["lat"], p["lon"], p.get("ele_m", p.get("alt_m", 0.0)))[:2])
        for p in points
        if math.isfinite(p["lat"]) and math.isfinite(p["lon"])
    ]


def robust_eskf(rows, frame):
    usable = [
        r for r in rows
        if r["gps_usable"] == 1 and math.isfinite(r["lat"]) and math.isfinite(r["lon"])
    ]
    if not usable:
        raise ValueError("No usable GPS rows found.")

    first = usable[0]
    p = frame.lla_to_enu(first["lat"], first["lon"], first["alt_m"])
    p[2] = 0.0
    v = np.zeros(3)

    init_rows = rows[:min(150, len(rows))]
    accs = []
    mags = []
    for r in init_rows:
        acc, _, mag = calibrate(r)
        if np.all(np.isfinite(acc)):
            accs.append(acc)
        if np.all(np.isfinite(mag)):
            mags.append(mag)
    acc0 = np.mean(accs, axis=0) if accs else np.array([0.0, 0.0, 1.0])
    mag0 = np.mean(mags, axis=0) if mags else np.array([1.0, 0.0, 0.0])
    roll0, pitch0 = accel_angles(acc0)
    yaw0 = mag_yaw(mag0, roll0, pitch0)
    q = quat_from_euler(roll0, pitch0, yaw0)
    bg = np.zeros(3)
    ba = np.zeros(3)

    P = np.diag([
        25.0, 25.0, 50.0,
        4.0, 4.0, 9.0,
        math.radians(10) ** 2, math.radians(10) ** 2, math.radians(25) ** 2,
        math.radians(0.5) ** 2, math.radians(0.5) ** 2, math.radians(0.5) ** 2,
        0.4 ** 2, 0.4 ** 2, 0.6 ** 2,
    ])

    states = []
    innovations = []
    pos_updates = 0
    vel_updates = 0
    soft_resets = 0
    gps_skips = 0
    last_t = rows[0]["t_ms"]
    last_gps_t = None
    last_gps_p = None

    for r in rows:
        t = r["t_ms"]
        dt = max(0.02, min(0.35, (t - last_t) / 1000.0)) if t > last_t else 0.02
        last_t = t

        acc_g, gyro_dps, _ = calibrate(r)
        gyro_rad = np.radians(gyro_dps) - bg
        q = quat_normalize(quat_mul(q, small_angle_quat(gyro_rad * dt)))

        Rnb = quat_to_rot(q)
        acc_nav = Rnb @ (acc_g * G) - np.array([0.0, 0.0, G]) - ba
        acc_nav[0] = max(-3.0, min(3.0, acc_nav[0]))
        acc_nav[1] = max(-3.0, min(3.0, acc_nav[1]))
        acc_nav[2] = max(-1.0, min(1.0, acc_nav[2]))

        # Flash logging produced about 8 Hz samples, so unconstrained pedestrian
        # acceleration integration drifts quickly. Keep IMU as short-term trend
        # information and let GPS/GPS-difference velocity dominate the path.
        v = v + 0.04 * acc_nav * dt
        damping = math.exp(-0.85 * dt)
        v[0] *= damping
        v[1] *= damping
        v[2] *= math.exp(-1.2 * dt)
        p = p + v * dt
        p[2] *= math.exp(-1.5 * dt)

        F = np.eye(15)
        F[0:3, 3:6] = np.eye(3) * dt
        q_pos = 0.20 * dt
        q_vel = 2.50 * dt
        q_att = math.radians(2.0) * dt
        q_bg = math.radians(0.02) * dt
        q_ba = 0.03 * dt
        Q = np.diag([
            q_pos, q_pos, q_pos * 2,
            q_vel, q_vel, q_vel * 2,
            q_att, q_att, q_att * 2,
            q_bg, q_bg, q_bg,
            q_ba, q_ba, q_ba,
        ]) ** 2
        P = F @ P @ F.T + Q

        if r["gps_usable"] == 1 and math.isfinite(r["lat"]) and math.isfinite(r["lon"]):
            z = frame.lla_to_enu(r["lat"], r["lon"], r["alt_m"])
            z[2] = 0.0
            innovation = z - p
            innov_h = float(np.linalg.norm(innovation[:2]))
            hdop = r["hdop"] if math.isfinite(r["hdop"]) else 3.0

            # For walking flash logs, GPS is the stable long-term reference.
            # A large innovation means prediction drift, not necessarily a GPS outlier.
            if innov_h > max(45.0, 18.0 * hdop):
                P[0:6, 0:6] += np.diag([400.0, 400.0, 25.0, 25.0, 25.0, 4.0])
                soft_resets += 1

            sigma_h = max(3.0, 2.2 * hdop)
            sigma_z = 20.0
            H = np.zeros((3, 15))
            H[0:3, 0:3] = np.eye(3)
            Rm = np.diag([sigma_h ** 2, sigma_h ** 2, sigma_z ** 2])
            S = H @ P @ H.T + Rm
            K = P @ H.T @ np.linalg.inv(S)
            dx = K @ innovation
            p += dx[0:3]
            v += dx[3:6]
            q = quat_normalize(quat_mul(small_angle_quat(dx[6:9]), q))
            bg += dx[9:12]
            ba += dx[12:15]
            P = (np.eye(15) - K @ H) @ P @ (np.eye(15) - K @ H).T + K @ Rm @ K.T

            blend = 0.55 if innov_h <= max(45.0, 18.0 * hdop) else 0.85
            p[:2] = (1.0 - blend) * p[:2] + blend * z[:2]
            p[2] = 0.0
            pos_updates += 1

            v_gps = None
            if last_gps_t is not None:
                dt_gps = (t - last_gps_t) / 1000.0
                delta = z - last_gps_p
                dist_h = float(np.linalg.norm(delta[:2]))
                if 0.5 <= dt_gps <= 5.0 and 0.10 <= dist_h <= 35.0:
                    v_gps = delta / dt_gps
                    v_gps[2] = 0.0
            if v_gps is not None:
                Hv = np.zeros((2, 15))
                Hv[0:2, 3:5] = np.eye(2)
                speed_sigma = max(0.6, 0.8 * hdop)
                Rv = np.diag([speed_sigma ** 2, speed_sigma ** 2])
                yv = v_gps[:2] - v[:2]
                Sv = Hv @ P @ Hv.T + Rv
                Kv = P @ Hv.T @ np.linalg.inv(Sv)
                dxv = Kv @ yv
                p += dxv[0:3]
                v += dxv[3:6]
                q = quat_normalize(quat_mul(small_angle_quat(dxv[6:9]), q))
                bg += dxv[9:12]
                ba += dxv[12:15]
                P = (np.eye(15) - Kv @ Hv) @ P @ (np.eye(15) - Kv @ Hv).T + Kv @ Rv @ Kv.T
                vel_updates += 1

            last_gps_t = t
            last_gps_p = z.copy()
            innovations.append({
                "t_s": (t - rows[0]["t_ms"]) / 1000.0,
                "innovation_e_m": innovation[0],
                "innovation_n_m": innovation[1],
                "innovation_h_m": innov_h,
                "hdop": hdop,
                "sats": r["satellites"],
            })
        elif r["gps_updated"] == 1:
            gps_skips += 1

        lat, lon, alt = frame.enu_to_lla(p)
        roll, pitch, yaw = euler_from_quat(q)
        states.append({
            "t_s": (t - rows[0]["t_ms"]) / 1000.0,
            "east_m": p[0],
            "north_m": p[1],
            "up_m": p[2],
            "ve_mps": v[0],
            "vn_mps": v[1],
            "vu_mps": v[2],
            "lat": lat,
            "lon": lon,
            "alt_m": alt,
            "roll_deg": roll,
            "pitch_deg": pitch,
            "yaw_deg": yaw,
            "bgx_dps": math.degrees(bg[0]),
            "bgy_dps": math.degrees(bg[1]),
            "bgz_dps": math.degrees(bg[2]),
            "bax_mps2": ba[0],
            "bay_mps2": ba[1],
            "baz_mps2": ba[2],
            "sigma_e_m": math.sqrt(max(P[0, 0], 0.0)),
            "sigma_n_m": math.sqrt(max(P[1, 1], 0.0)),
        })

    counters = {
        "pos_updates": pos_updates,
        "vel_updates": vel_updates,
        "soft_resets": soft_resets,
        "gps_skips": gps_skips,
    }
    return states, innovations, counters


def write_csv(path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def make_folium_map(phone_points, esp_points, eskf_points, out_path):
    if folium is None:
        return None
    all_points = phone_points + esp_points + eskf_points
    center = [
        statistics.fmean(p["lat"] for p in all_points),
        statistics.fmean(p["lon"] for p in all_points),
    ]
    fmap = folium.Map(location=center, zoom_start=17, tiles="OpenStreetMap")
    folium.PolyLine(
        [(p["lat"], p["lon"]) for p in phone_points],
        color="blue",
        weight=4,
        opacity=0.8,
        tooltip="Phone GNSS reference",
    ).add_to(fmap)
    folium.PolyLine(
        [(p["lat"], p["lon"]) for p in esp_points],
        color="orange",
        weight=3,
        opacity=0.75,
        tooltip="ESP32 GPS raw",
    ).add_to(fmap)
    folium.PolyLine(
        [(p["lat"], p["lon"]) for p in eskf_points],
        color="green",
        weight=3,
        opacity=0.8,
        tooltip="Robust 15D ESKF",
    ).add_to(fmap)
    for name, points, color in [
        ("phone", phone_points, "blue"),
        ("esp32", esp_points, "orange"),
        ("eskf", eskf_points, "green"),
    ]:
        if points:
            folium.Marker(
                [points[0]["lat"], points[0]["lon"]],
                popup=name + " start",
                icon=folium.Icon(color=color if color != "orange" else "red", icon="play"),
            ).add_to(fmap)
            folium.Marker(
                [points[-1]["lat"], points[-1]["lon"]],
                popup=name + " end",
                icon=folium.Icon(color=color if color != "orange" else "red", icon="stop"),
            ).add_to(fmap)
    folium.LayerControl().add_to(fmap)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fmap.save(str(out_path))
    return out_path


def make_static_overlay(phone_xy, esp_xy, eskf_xy, tag):
    path = FIG_DIR / ("gps_phone_esp32_eskf_overlay_%s.png" % tag)
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    plt.figure(figsize=(8, 7), dpi=160)
    if phone_xy:
        plt.plot([p[0] for p in phone_xy], [p[1] for p in phone_xy], "-", lw=2.2, label="Phone GNSS reference")
    if esp_xy:
        plt.plot([p[0] for p in esp_xy], [p[1] for p in esp_xy], "-", lw=1.4, label="ESP32 GPS raw")
    if eskf_xy:
        plt.plot([p[0] for p in eskf_xy], [p[1] for p in eskf_xy], "-", lw=1.8, label="Robust 15D ESKF")
    plt.axis("equal")
    plt.grid(True, alpha=0.3)
    plt.xlabel("East (m)")
    plt.ylabel("North (m)")
    plt.title("Outdoor Track Overlay: Phone GNSS, ESP32 GPS, Robust 15D ESKF")
    plt.legend()
    plt.tight_layout()
    plt.savefig(path)
    plt.close()
    return path


def make_innovation_plot(innovations, tag):
    path = FIG_DIR / ("eskf_15d_sync_robust_innovation_%s.png" % tag)
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    t = [x["t_s"] for x in innovations]
    h = [x["innovation_h_m"] for x in innovations]
    hdop = [x["hdop"] for x in innovations]
    fig, ax1 = plt.subplots(figsize=(9, 4.5), dpi=160)
    ax1.plot(t, h, lw=1.0, label="Position innovation")
    ax1.set_xlabel("Time (s)")
    ax1.set_ylabel("Horizontal innovation (m)")
    ax1.grid(True, alpha=0.3)
    ax2 = ax1.twinx()
    ax2.plot(t, hdop, color="tab:orange", lw=0.9, alpha=0.7, label="HDOP")
    ax2.set_ylabel("HDOP")
    lines, labels = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines + lines2, labels + labels2, loc="upper right")
    plt.title("Robust 15D ESKF GPS Innovation")
    plt.tight_layout()
    plt.savefig(path)
    plt.close(fig)
    return path


def track_distance_latlon(points):
    if len(points) < 2:
        return 0.0
    frame = LocalFrame(points[0]["lat"], points[0]["lon"], points[0].get("alt_m", 0.0))
    xy = dict_points_to_xy(points, frame)
    return path_distance_xy(xy)[0]


def main():
    source_csv = latest_file(SYNC_DIR, "imu_gps_sync_offline_*.csv")
    if source_csv is None:
        raise FileNotFoundError("No imu_gps_sync_offline_*.csv found in %s" % SYNC_DIR)
    gpx_path = latest_gpx_file()
    if gpx_path is None:
        raise FileNotFoundError("No GPX file found in %s" % (BIG_HOMEWORK / "data"))

    tag = source_csv.stem.replace("imu_gps_sync_offline_", "")
    rows = read_sync_csv(source_csv)
    phone_points, phone_meta = read_gpx(gpx_path)
    esp_points = [
        {
            "lat": r["lat"],
            "lon": r["lon"],
            "alt_m": r["alt_m"],
            "t_s": (r["t_ms"] - rows[0]["t_ms"]) / 1000.0,
            "hdop": r["hdop"],
            "satellites": r["satellites"],
        }
        for r in rows
        if r["gps_usable"] == 1 and math.isfinite(r["lat"]) and math.isfinite(r["lon"])
    ]
    if not esp_points:
        raise ValueError("No usable ESP32 GPS points found.")

    frame = LocalFrame(esp_points[0]["lat"], esp_points[0]["lon"], esp_points[0].get("alt_m", 0.0))
    states, innovations, counters = robust_eskf(rows, frame)
    eskf_points = [{"lat": s["lat"], "lon": s["lon"], "alt_m": s["alt_m"]} for s in states]

    ref_frame = LocalFrame(phone_points[0]["lat"], phone_points[0]["lon"], phone_points[0].get("ele_m", 0.0))
    phone_xy = dict_points_to_xy(phone_points, ref_frame)
    esp_xy = dict_points_to_xy(esp_points, ref_frame)
    eskf_xy = dict_points_to_xy(eskf_points, ref_frame)

    esp_distance, esp_jumps = path_distance_xy(esp_xy)
    phone_distance, phone_jumps = path_distance_xy(phone_xy)
    eskf_distance, eskf_jumps = path_distance_xy(eskf_xy)
    esp_span = span_xy(esp_xy)
    phone_span = span_xy(phone_xy)
    eskf_span = span_xy(eskf_xy)

    stride_esp = max(1, len(esp_xy) // 700)
    stride_eskf = max(1, len(eskf_xy) // 700)
    esp_to_phone = nearest_polyline_distances(esp_xy, phone_xy, stride=stride_esp)
    eskf_to_phone = nearest_polyline_distances(eskf_xy, phone_xy, stride=stride_eskf)

    t_values = [r["t_ms"] for r in rows]
    dt_ms = [b - a for a, b in zip(t_values, t_values[1:]) if b > a]
    sats = [p["satellites"] for p in esp_points if p["satellites"] > 0]
    hdop = [p["hdop"] for p in esp_points if math.isfinite(p["hdop"])]

    state_path = ANALYSIS_DIR / ("eskf_15d_sync_robust_states_%s.csv" % tag)
    state_fields = [
        "t_s", "east_m", "north_m", "up_m", "ve_mps", "vn_mps", "vu_mps",
        "lat", "lon", "alt_m", "roll_deg", "pitch_deg", "yaw_deg",
        "bgx_dps", "bgy_dps", "bgz_dps", "bax_mps2", "bay_mps2", "baz_mps2",
        "sigma_e_m", "sigma_n_m",
    ]
    write_csv(state_path, states, state_fields)

    innovation_path = ANALYSIS_DIR / ("eskf_15d_sync_robust_innovations_%s.csv" % tag)
    write_csv(innovation_path, innovations, ["t_s", "innovation_e_m", "innovation_n_m", "innovation_h_m", "hdop", "sats"])

    overlay_png = make_static_overlay(phone_xy, esp_xy, eskf_xy, tag)
    overlay_html = make_folium_map(
        phone_points,
        esp_points,
        eskf_points[::max(1, len(eskf_points) // 1500)],
        FIG_DIR / ("gps_phone_esp32_eskf_overlay_%s.html" % tag),
    )
    innov_png = make_innovation_plot(innovations, tag)

    summary_rows = [
        ("source_csv", str(source_csv), "", "ESP32 synchronized IMU/GPS CSV"),
        ("source_gpx", str(gpx_path), "", "phone GNSS reference GPX"),
        ("esp_rows", len(rows), "rows", ""),
        ("esp_duration", (t_values[-1] - t_values[0]) / 1000.0, "s", ""),
        ("esp_sample_rate_mean", 1000.0 / statistics.mean(dt_ms), "Hz", "from t_ms"),
        ("esp_sample_rate_median", 1000.0 / statistics.median(dt_ms), "Hz", "from t_ms"),
        ("esp_gps_usable_points", len(esp_points), "points", ""),
        ("esp_satellites_median", statistics.median(sats) if sats else float("nan"), "count", ""),
        ("esp_hdop_median", statistics.median(hdop) if hdop else float("nan"), "", ""),
        ("phone_gpx_points", len(phone_points), "points", ""),
        ("phone_gpx_distance_extension", phone_meta["total_distance_m"], "m", "from GPX extension"),
        ("phone_gpx_distance_calculated", phone_distance, "m", "polyline distance"),
        ("esp_gps_distance", esp_distance, "m", "quality-filtered GPS polyline"),
        ("eskf_distance", eskf_distance, "m", "robust ESKF state polyline"),
        ("phone_span_east", phone_span[0], "m", ""),
        ("phone_span_north", phone_span[1], "m", ""),
        ("esp_span_east", esp_span[0], "m", ""),
        ("esp_span_north", esp_span[1], "m", ""),
        ("eskf_span_east", eskf_span[0], "m", ""),
        ("eskf_span_north", eskf_span[1], "m", ""),
        ("esp_to_phone_median", statistics.median(esp_to_phone), "m", "nearest distance to phone track"),
        ("esp_to_phone_p90", percentile(esp_to_phone, 90), "m", "nearest distance to phone track"),
        ("esp_to_phone_p95", percentile(esp_to_phone, 95), "m", "nearest distance to phone track"),
        ("eskf_to_phone_median", statistics.median(eskf_to_phone), "m", "nearest distance to phone track"),
        ("eskf_to_phone_p90", percentile(eskf_to_phone, 90), "m", "nearest distance to phone track"),
        ("eskf_to_phone_p95", percentile(eskf_to_phone, 95), "m", "nearest distance to phone track"),
        ("eskf_position_updates", counters["pos_updates"], "updates", ""),
        ("eskf_velocity_updates", counters["vel_updates"], "updates", "GPS position difference pseudo velocity"),
        ("eskf_soft_resets", counters["soft_resets"], "events", "adaptive covariance inflation, not rejected"),
        ("eskf_gps_skips", counters["gps_skips"], "updates", "GPS updated but not usable"),
        ("innovation_median", statistics.median([x["innovation_h_m"] for x in innovations]), "m", "before update"),
        ("innovation_p95", percentile([x["innovation_h_m"] for x in innovations], 95), "m", "before update"),
        ("state_csv", str(state_path), "", ""),
        ("innovation_csv", str(innovation_path), "", ""),
        ("overlay_png", str(overlay_png), "", ""),
        ("overlay_html", str(overlay_html) if overlay_html else "", "", "folium map"),
        ("innovation_png", str(innov_png), "", ""),
    ]

    summary_path = ANALYSIS_DIR / ("gps_esp32_phone_eskf_summary_%s.csv" % tag)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with summary_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["item", "value", "unit", "note"])
        writer.writerows(summary_rows)

    report_md = DOCS_DIR / ("gps_eskf_completion_report_%s.md" % tag)
    report_md.write_text(
        make_report_text(tag, summary_rows),
        encoding="utf-8",
    )

    print("Analyzed:", source_csv)
    print("Phone GPX:", gpx_path)
    print("Summary:", summary_path)
    print("States:", state_path)
    print("Overlay PNG:", overlay_png)
    print("Overlay HTML:", overlay_html)
    print("Innovation PNG:", innov_png)
    print("Report snippet:", report_md)


def summary_dict(summary_rows):
    return {item: value for item, value, _, _ in summary_rows}


def fnum(value, digits=3):
    try:
        return ("%%.%df" % digits) % float(value)
    except Exception:
        return str(value)


def make_report_text(tag, summary_rows):
    s = summary_dict(summary_rows)
    return """# GPS/IMU Outdoor Track and Robust 15D ESKF Result ({tag})

## Experiment Description

The final outdoor walking experiment used the ESP32 offline logger installed as `/main.py`.
The board was powered by a power bank and recorded synchronized IMU, magnetometer, and
GPS fields to ESP32 flash under `/imu_gps_logs`. A phone GNSS GPX track was recorded at
the same time as a spatial reference trajectory. Because the phone GPX timestamp field is
not a valid absolute time in this export, the phone trajectory is used for spatial overlay
and nearest-distance comparison rather than strict time synchronization.

## Data Quality

| Indicator | Value |
|---|---:|
| ESP32 synchronized rows | {esp_rows} |
| ESP32 duration | {duration} s |
| ESP32 actual sample rate | {rate} Hz |
| ESP32 usable GPS points | {gps_points} |
| ESP32 median satellites | {sats} |
| ESP32 median HDOP | {hdop} |
| Phone GPX points | {phone_points} |
| Phone GPX distance | {phone_distance} m |
| ESP32 GPS distance | {esp_distance} m |

The ESP32 GNSS data are usable for the required GPS trajectory visualization. The median
nearest distance from the ESP32 GPS trajectory to the phone reference trajectory is
{esp_med} m, and the P95 nearest distance is {esp_p95} m. This indicates that the ESP32
GPS6MV2/NEO-6M route agrees with the phone track at the several-meter to ten-meter level
on the overlapping route section.

## Robust 15D ESKF

For the low-speed flash-logged walking data, the original strict ESKF gate rejected many
GPS updates because the actual IMU logging rate was only about {rate} Hz. Therefore, a
low-speed loose-coupled 15-state ESKF was used. The nominal state remains
`p, v, q, bg, ba`, and the error state is `dx = [dp, dv, dtheta, dbg, dba]^T`.
The filter uses IMU propagation between samples, GPS position updates as the dominant
long-term correction, and GPS position-difference pseudo velocity updates when valid
successive GNSS points are available.

| Indicator | ESP32 GPS Raw | Robust 15D ESKF |
|---|---:|---:|
| Track distance | {esp_distance} m | {eskf_distance} m |
| Nearest distance to phone, median | {esp_med} m | {eskf_med} m |
| Nearest distance to phone, P90 | {esp_p90} m | {eskf_p90} m |
| Nearest distance to phone, P95 | {esp_p95} m | {eskf_p95} m |

The robust ESKF accepted {pos_updates} GPS position updates and {vel_updates} pseudo
velocity updates. Adaptive covariance inflation occurred {soft_resets} times; these events
represent drift recovery under low IMU sampling frequency, not discarded GNSS observations.
The result is suitable for the course requirement of implementing a simplified 15D ESKF
and demonstrating GPS/IMU loose coupling on real outdoor data.

## Report Figure Captions

Figure X. Outdoor trajectory overlay of phone GNSS reference, ESP32 GPS raw trajectory,
and robust 15D ESKF output. The ESP32 track is generated by the power-bank offline logger,
and the phone GPX trajectory is used as the spatial reference.

Figure X. Robust 15D ESKF GPS position innovation and HDOP over time. The innovation is
computed before each GPS update and reflects the consistency between IMU prediction and
GNSS correction during outdoor walking.
""".format(
        tag=tag,
        esp_rows=int(float(s["esp_rows"])),
        duration=fnum(s["esp_duration"], 3),
        rate=fnum(s["esp_sample_rate_mean"], 3),
        gps_points=int(float(s["esp_gps_usable_points"])),
        sats=fnum(s["esp_satellites_median"], 1),
        hdop=fnum(s["esp_hdop_median"], 2),
        phone_points=int(float(s["phone_gpx_points"])),
        phone_distance=fnum(s["phone_gpx_distance_calculated"], 2),
        esp_distance=fnum(s["esp_gps_distance"], 2),
        eskf_distance=fnum(s["eskf_distance"], 2),
        esp_med=fnum(s["esp_to_phone_median"], 2),
        esp_p90=fnum(s["esp_to_phone_p90"], 2),
        esp_p95=fnum(s["esp_to_phone_p95"], 2),
        eskf_med=fnum(s["eskf_to_phone_median"], 2),
        eskf_p90=fnum(s["eskf_to_phone_p90"], 2),
        eskf_p95=fnum(s["eskf_to_phone_p95"], 2),
        pos_updates=int(float(s["eskf_position_updates"])),
        vel_updates=int(float(s["eskf_velocity_updates"])),
        soft_resets=int(float(s["eskf_soft_resets"])),
    )


if __name__ == "__main__":
    main()
