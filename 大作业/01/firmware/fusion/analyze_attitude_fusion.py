# -*- coding: utf-8 -*-
"""
Analyze attitude fusion experiment data.

Algorithms:
1. Complementary filter
2. Mahony AHRS

Input: latest group of data/attitude_fusion/attitude_*.csv
Output:
  data/analysis/attitude_fusion_static_std.csv
  data/analysis/attitude_fusion_update_rate.csv
  data/analysis/attitude_fusion_latest.csv
  data/figures/attitude_*.png
"""

from pathlib import Path
import csv
import math
import time
from collections import defaultdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data" / "attitude_fusion"
ANALYSIS_DIR = ROOT / "data" / "analysis"
FIG_DIR = ROOT / "data" / "figures"

ACCEL_BIAS = np.array([0.01039430, 0.00708252, 0.00648056])
ACCEL_SCALE = np.array([0.99660411, 0.99663985, 1.01721639])

MAG_BIAS = np.array([77.082135, -94.427834, -36.852085])
MAG_MATRIX = np.array([
    [1.006948, -0.000000, 0.000000],
    [-0.000000, 1.020430, 0.000000],
    [0.000000, 0.000000, 1.043697],
])
GYRO_BIAS_DPS = np.array([0.228303741, 0.964654373, -0.100939275])


def latest_timestamp_group():
    files = sorted(DATA_DIR.glob("attitude_*_*.csv"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise FileNotFoundError("No attitude_*.csv found in %s" % DATA_DIR)
    grouped = defaultdict(list)
    for path in files:
        stem = path.stem
        timestamp = "_".join(stem.split("_")[-2:])
        grouped[timestamp].append(path)
    timestamp = sorted(grouped, key=lambda k: max(p.stat().st_mtime for p in grouped[k]))[-1]
    return timestamp, sorted(grouped[timestamp])


def read_csv(path):
    rows = []
    with path.open("r", encoding="utf-8") as f:
        reader = csv.reader(line for line in f if not line.startswith("#"))
        header = next(reader)
        idx = {name: header.index(name) for name in header}
        for row in reader:
            if not row:
                continue
            rows.append({
                "phase": row[idx["label"]],
                "t_ms": float(row[idx["t_ms"]]),
                "ax": float(row[idx["ax_g"]]),
                "ay": float(row[idx["ay_g"]]),
                "az": float(row[idx["az_g"]]),
                "temp": float(row[idx["temp_c"]]),
                "gx": float(row[idx["gx_dps"]]),
                "gy": float(row[idx["gy_dps"]]),
                "gz": float(row[idx["gz_dps"]]),
                "mx": float(row[idx["mx_raw"]]),
                "my": float(row[idx["my_raw"]]),
                "mz": float(row[idx["mz_raw"]]),
            })
    return rows


def normalize(v):
    n = float(np.linalg.norm(v))
    if n < 1e-12:
        return v
    return v / n


def wrap_deg(angle):
    while angle > 180:
        angle -= 360
    while angle < -180:
        angle += 360
    return angle


def accel_angles(ax, ay, az):
    roll = math.degrees(math.atan2(ay, az))
    pitch = math.degrees(math.atan2(-ax, math.sqrt(ay * ay + az * az)))
    return roll, pitch


def mag_yaw(mx, my, mz, roll_deg, pitch_deg):
    roll = math.radians(roll_deg)
    pitch = math.radians(pitch_deg)
    mx2 = mx * math.cos(pitch) + mz * math.sin(pitch)
    my2 = (
        mx * math.sin(roll) * math.sin(pitch)
        + my * math.cos(roll)
        - mz * math.sin(roll) * math.cos(pitch)
    )
    return math.degrees(math.atan2(-my2, mx2))


def quat_mul(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return np.array([
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    ])


def quat_from_euler(roll_deg, pitch_deg, yaw_deg):
    cr = math.cos(math.radians(roll_deg) / 2)
    sr = math.sin(math.radians(roll_deg) / 2)
    cp = math.cos(math.radians(pitch_deg) / 2)
    sp = math.sin(math.radians(pitch_deg) / 2)
    cy = math.cos(math.radians(yaw_deg) / 2)
    sy = math.sin(math.radians(yaw_deg) / 2)
    return np.array([
        cr * cp * cy + sr * sp * sy,
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
    ])


def euler_from_quat(q):
    q0, q1, q2, q3 = q
    roll = math.atan2(2 * (q0 * q1 + q2 * q3), 1 - 2 * (q1 * q1 + q2 * q2))
    s = 2 * (q0 * q2 - q3 * q1)
    s = max(-1.0, min(1.0, s))
    pitch = math.asin(s)
    yaw = math.atan2(2 * (q0 * q3 + q1 * q2), 1 - 2 * (q2 * q2 + q3 * q3))
    return math.degrees(roll), math.degrees(pitch), math.degrees(yaw)


class Mahony:
    def __init__(self, kp=1.4, ki=0.02):
        self.kp = kp
        self.ki = ki
        self.q = np.array([1.0, 0.0, 0.0, 0.0])
        self.integral = np.zeros(3)
        self.initialized = False

    def update(self, gyro_dps, acc_g, mag_raw, dt):
        acc = normalize(acc_g)
        mag = normalize(mag_raw)

        if not self.initialized:
            r, p = accel_angles(acc[0], acc[1], acc[2])
            y = mag_yaw(mag[0], mag[1], mag[2], r, p)
            self.q = normalize(quat_from_euler(r, p, y))
            self.initialized = True

        q0, q1, q2, q3 = self.q
        v_gravity = np.array([
            2 * (q1 * q3 - q0 * q2),
            2 * (q0 * q1 + q2 * q3),
            q0 * q0 - q1 * q1 - q2 * q2 + q3 * q3,
        ])

        h = quat_mul(self.q, quat_mul(np.array([0.0, mag[0], mag[1], mag[2]]), np.array([q0, -q1, -q2, -q3])))
        bx = math.sqrt(h[1] * h[1] + h[2] * h[2])
        bz = h[3]
        v_mag = np.array([
            2 * bx * (0.5 - q2 * q2 - q3 * q3) + 2 * bz * (q1 * q3 - q0 * q2),
            2 * bx * (q1 * q2 - q0 * q3) + 2 * bz * (q0 * q1 + q2 * q3),
            2 * bx * (q0 * q2 + q1 * q3) + 2 * bz * (0.5 - q1 * q1 - q2 * q2),
        ])

        error = np.cross(v_gravity, acc) + np.cross(v_mag, mag)
        self.integral += error * dt
        gyro = np.radians(gyro_dps) + self.kp * error + self.ki * self.integral
        q_dot = 0.5 * quat_mul(self.q, np.array([0.0, gyro[0], gyro[1], gyro[2]]))
        self.q = normalize(self.q + q_dot * dt)
        return euler_from_quat(self.q)


def calibrate_row(row):
    acc = (np.array([row["ax"], row["ay"], row["az"]]) - ACCEL_BIAS) / ACCEL_SCALE
    gyro = np.array([row["gx"], row["gy"], row["gz"]]) - GYRO_BIAS_DPS
    mag = MAG_MATRIX @ (np.array([row["mx"], row["my"], row["mz"]]) - MAG_BIAS)
    return acc, gyro, mag


def run_filters(rows):
    comp_alpha = 0.98
    out = []
    comp_initialized = False
    cr = cp = cy = 0.0
    mr = mp = my = 0.0
    mi = np.zeros(3)
    mahony_initialized = False
    mahony_kp = 0.08
    mahony_ki = 0.004

    last_t = rows[0]["t_ms"] / 1000.0
    comp_start = time.perf_counter()
    comp_time = 0.0
    mahony_time = 0.0

    for row in rows:
        t = row["t_ms"] / 1000.0
        dt = max(1e-3, min(0.1, t - last_t))
        last_t = t
        acc, gyro, mag = calibrate_row(row)

        t0 = time.perf_counter()
        ar, ap = accel_angles(acc[0], acc[1], acc[2])
        myaw = mag_yaw(mag[0], mag[1], mag[2], ar, ap)
        if not comp_initialized:
            cr, cp, cy = ar, ap, myaw
            comp_initialized = True
        else:
            cr = comp_alpha * (cr + gyro[0] * dt) + (1 - comp_alpha) * ar
            cp = comp_alpha * (cp + gyro[1] * dt) + (1 - comp_alpha) * ap
            yaw_pred = cy + gyro[2] * dt
            yaw_err = wrap_deg(myaw - yaw_pred)
            cy = wrap_deg(yaw_pred + (1 - comp_alpha) * yaw_err)
        comp_time += time.perf_counter() - t0

        t0 = time.perf_counter()
        if not mahony_initialized:
            mr, mp, my = ar, ap, myaw
            mahony_initialized = True
        else:
            pred = np.array([
                mr + gyro[0] * dt,
                mp + gyro[1] * dt,
                wrap_deg(my + gyro[2] * dt),
            ])
            err = np.array([
                wrap_deg(ar - pred[0]),
                wrap_deg(ap - pred[1]),
                wrap_deg(myaw - pred[2]),
            ])
            mi += err * dt
            corrected = pred + mahony_kp * err + mahony_ki * mi
            mr = corrected[0]
            mp = corrected[1]
            my = wrap_deg(corrected[2])
        mahony_time += time.perf_counter() - t0

        out.append({
            "phase": row["phase"],
            "t_s": t,
            "temp_c": row["temp"],
            "comp_roll": cr,
            "comp_pitch": cp,
            "comp_yaw": cy,
            "mahony_roll": mr,
            "mahony_pitch": mp,
            "mahony_yaw": my,
        })

    elapsed = rows[-1]["t_ms"] / 1000.0 - rows[0]["t_ms"] / 1000.0
    stats = {
        "samples": len(rows),
        "data_duration_s": elapsed,
        "sample_rate_hz": len(rows) / elapsed if elapsed > 0 else 0,
        "complementary_update_hz": len(rows) / comp_time if comp_time > 0 else 0,
        "mahony_update_hz": len(rows) / mahony_time if mahony_time > 0 else 0,
        "analysis_total_s": time.perf_counter() - comp_start,
    }
    return out, stats


def write_outputs(timestamp, fused, update_stats):
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    fused_path = ANALYSIS_DIR / "attitude_fusion_latest.csv"
    keys = list(fused[0].keys())
    with fused_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(fused)

    static_path = ANALYSIS_DIR / "attitude_fusion_static_std.csv"
    with static_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["phase", "algorithm", "roll_std_deg", "pitch_std_deg", "yaw_std_deg", "roll_mean_deg", "pitch_mean_deg", "yaw_mean_deg"])
        for phase in ("level_static", "tilt_static"):
            part = [r for r in fused if r["phase"] == phase]
            if not part:
                continue
            for alg in ("comp", "mahony"):
                vals = np.array([[r[f"{alg}_roll"], r[f"{alg}_pitch"], r[f"{alg}_yaw"]] for r in part])
                writer.writerow([
                    phase,
                    "complementary" if alg == "comp" else "mahony",
                    "%.6f" % np.std(vals[:, 0]),
                    "%.6f" % np.std(vals[:, 1]),
                    "%.6f" % np.std(vals[:, 2]),
                    "%.6f" % np.mean(vals[:, 0]),
                    "%.6f" % np.mean(vals[:, 1]),
                    "%.6f" % np.mean(vals[:, 2]),
                ])

    rate_path = ANALYSIS_DIR / "attitude_fusion_update_rate.csv"
    with rate_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["item", "value", "unit"])
        for key, val in update_stats.items():
            unit = "Hz" if key.endswith("_hz") else "s" if key.endswith("_s") else "rows"
            writer.writerow([key, "%.6f" % val, unit])

    make_figures(timestamp, fused)
    return fused_path, static_path, rate_path


def plot_phase(fused, phase, fig_name, title):
    part = [r for r in fused if r["phase"] == phase]
    if not part:
        return None
    t0 = part[0]["t_s"]
    t = np.array([r["t_s"] - t0 for r in part])
    fig, axes = plt.subplots(3, 1, figsize=(10, 7.2), sharex=True)
    channels = [("roll", "Roll (deg)"), ("pitch", "Pitch (deg)"), ("yaw", "Yaw (deg)")]
    for ax, (name, ylabel) in zip(axes, channels):
        ax.plot(t, [r[f"comp_{name}"] for r in part], label="Complementary", color="#f97316", linewidth=1)
        ax.plot(t, [r[f"mahony_{name}"] for r in part], label="Mahony", color="#2563eb", linewidth=1)
        ax.set_ylabel(ylabel)
        ax.grid(True, alpha=0.25)
    axes[0].set_title(title)
    axes[-1].set_xlabel("Time (s)")
    axes[0].legend(loc="upper right")
    fig.tight_layout()
    path = FIG_DIR / fig_name
    fig.savefig(path, dpi=180)
    plt.close(fig)
    return path


def make_figures(timestamp, fused):
    plot_phase(fused, "level_static", "attitude_level_static_rpy.png", "Level static attitude")
    plot_phase(fused, "tilt_static", "attitude_tilt_static_rpy.png", "Fixed tilt attitude")
    plot_phase(fused, "shake_return_level", "attitude_shake_return_response.png", "Shake and return-to-level response")
    plot_phase(fused, "continuous_motion", "attitude_continuous_motion_rpy.png", "Continuous manual motion attitude")


def main():
    timestamp, files = latest_timestamp_group()
    all_rows = []
    t_offset = 0.0
    for path in files:
        rows = read_csv(path)
        if not rows:
            continue
        for row in rows:
            row["t_ms"] += t_offset
        t_offset = rows[-1]["t_ms"] + 1000.0
        all_rows.extend(rows)

    fused, update_stats = run_filters(all_rows)
    fused_path, static_path, rate_path = write_outputs(timestamp, fused, update_stats)

    print("Timestamp group:", timestamp)
    print("Input files:")
    for path in files:
        print(" ", path)
    print("Samples:", len(all_rows))
    print("Estimated sample rate: %.3f Hz" % update_stats["sample_rate_hz"])
    print("Complementary update rate: %.1f Hz" % update_stats["complementary_update_hz"])
    print("Mahony update rate: %.1f Hz" % update_stats["mahony_update_hz"])
    print("Wrote:", fused_path)
    print("Wrote:", static_path)
    print("Wrote:", rate_path)
    print("Figures saved to:", FIG_DIR)


if __name__ == "__main__":
    main()
