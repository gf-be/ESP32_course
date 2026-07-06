# -*- coding: utf-8 -*-
"""
Analyze attitude fusion data with three algorithms:

1. Complementary filter
2. Mahony-style PI filter
3. Madgwick MARG filter

The script reads the latest attitude_fusion CSV group, applies the latest
accelerometer, gyro, and magnetometer calibration parameters when available,
then writes report-ready CSV summaries and figures.
"""

from collections import defaultdict
from pathlib import Path
import csv
import math
import time

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


PHASES_STATIC = ("level_static", "tilt_static")
PHASES_PLOT = [
    ("level_static", "attitude_level_static_rpy.png", "Level static attitude"),
    ("tilt_static", "attitude_tilt_static_rpy.png", "Fixed tilt attitude"),
    ("shake_return_level", "attitude_shake_return_response.png", "Shake and return-to-level response"),
    ("continuous_motion", "attitude_continuous_motion_rpy.png", "Continuous manual motion attitude"),
]
PHASE_ORDER = {
    "level_static": 0,
    "tilt_static": 1,
    "shake_return_level": 2,
    "continuous_motion": 3,
}


GYRO_BIAS_DPS = np.array([0.228303741, 0.964654373, -0.100939275])
DEFAULT_ACCEL_C = np.diag([1.0 / 0.99660411, 1.0 / 0.99663985, 1.0 / 1.01721639])
DEFAULT_ACCEL_D = -DEFAULT_ACCEL_C @ np.array([0.01039430, 0.00708252, 0.00648056])
MAG_BIAS = np.array([77.082135, -94.427834, -36.852085])
MAG_MATRIX = np.array([
    [1.0102826701, 0.0065974430, -0.0096782755],
    [0.0065974430, 0.9756936862, -0.0109598281],
    [-0.0096782755, -0.0109598281, 1.0154785728],
])


def find_project_root():
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "data").is_dir() and (parent / "firmware").is_dir():
            return parent
    return here.parent


PROJECT_ROOT = find_project_root()
DATA_DIR_CANDIDATES = [
    PROJECT_ROOT / "data" / "fusion_comparison",
    PROJECT_ROOT / "data" / "attitude_fusion",
    PROJECT_ROOT.parent / "data" / "attitude_fusion",
]
ANALYSIS_DIR = PROJECT_ROOT / "data"
FIG_DIR = PROJECT_ROOT / "data" / "figures"


def latest_timestamp_group():
    for data_dir in DATA_DIR_CANDIDATES:
        if not data_dir.exists():
            continue
        files = sorted(data_dir.glob("attitude_*_*.csv"), key=lambda p: p.stat().st_mtime)
        files = [p for p in files if not p.name.endswith("_notes.txt")]
        if not files:
            continue
        grouped = defaultdict(list)
        for path in files:
            stem = path.stem
            timestamp = "_".join(stem.split("_")[-2:])
            grouped[timestamp].append(path)
        timestamp = sorted(grouped, key=lambda k: max(p.stat().st_mtime for p in grouped[k]))[-1]
        def file_order(path):
            for phase, order in PHASE_ORDER.items():
                if phase in path.stem:
                    return order
            return 99

        return data_dir, timestamp, sorted(grouped[timestamp], key=file_order)
    raise FileNotFoundError("No attitude_*.csv files found in expected data folders")


def read_csv(path):
    rows = []
    with path.open("r", encoding="utf-8") as f:
        reader = csv.reader(line for line in f if not line.startswith("#") and line.strip())
        header = next(reader)
        idx = {name: header.index(name) for name in header}
        for row in reader:
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


def load_accel_calibration():
    path = PROJECT_ROOT / "data" / "accel_6pos_12param_inverse.csv"
    if not path.exists():
        return DEFAULT_ACCEL_C, DEFAULT_ACCEL_D, "default diagonal 6-parameter"

    rows = list(csv.DictReader(path.open("r", encoding="utf-8")))
    c = np.zeros((3, 3))
    d = np.zeros(3)
    for i, row in enumerate(rows):
        c[i, 0] = float(row["raw_x_coeff"])
        c[i, 1] = float(row["raw_y_coeff"])
        c[i, 2] = float(row["raw_z_coeff"])
        d[i] = float(row["offset_g"])
    return c, d, path.name


ACCEL_C, ACCEL_D, ACCEL_CAL_SOURCE = load_accel_calibration()


def normalize(v):
    n = float(np.linalg.norm(v))
    if n < 1e-12:
        return v.copy()
    return v / n


def wrap_deg(angle):
    while angle > 180.0:
        angle -= 360.0
    while angle < -180.0:
        angle += 360.0
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


class Madgwick:
    def __init__(self, beta=0.035):
        self.beta = beta
        self.q = np.array([1.0, 0.0, 0.0, 0.0])
        self.initialized = False

    def initialize(self, acc, mag):
        r, p = accel_angles(acc[0], acc[1], acc[2])
        y = mag_yaw(mag[0], mag[1], mag[2], r, p)
        self.q = normalize(quat_from_euler(r, p, y))
        self.initialized = True

    def update(self, gyro_dps, acc_g, mag_raw, dt):
        acc = normalize(acc_g)
        mag = normalize(mag_raw)
        if not self.initialized:
            self.initialize(acc, mag)

        q1, q2, q3, q4 = self.q
        gx, gy, gz = np.radians(gyro_dps)
        ax, ay, az = acc
        mx, my, mz = mag

        _2q1mx = 2.0 * q1 * mx
        _2q1my = 2.0 * q1 * my
        _2q1mz = 2.0 * q1 * mz
        _2q2mx = 2.0 * q2 * mx
        _2q1 = 2.0 * q1
        _2q2 = 2.0 * q2
        _2q3 = 2.0 * q3
        _2q4 = 2.0 * q4
        _2q1q3 = 2.0 * q1 * q3
        _2q3q4 = 2.0 * q3 * q4
        q1q1 = q1 * q1
        q1q2 = q1 * q2
        q1q3 = q1 * q3
        q1q4 = q1 * q4
        q2q2 = q2 * q2
        q2q3 = q2 * q3
        q2q4 = q2 * q4
        q3q3 = q3 * q3
        q3q4 = q3 * q4
        q4q4 = q4 * q4

        hx = (
            mx * q1q1
            - _2q1my * q4
            + _2q1mz * q3
            + mx * q2q2
            + _2q2 * my * q3
            + _2q2 * mz * q4
            - mx * q3q3
            - mx * q4q4
        )
        hy = (
            _2q1mx * q4
            + my * q1q1
            - _2q1mz * q2
            + _2q2mx * q3
            - my * q2q2
            + my * q3q3
            + _2q3 * mz * q4
            - my * q4q4
        )
        _2bx = math.sqrt(hx * hx + hy * hy)
        _2bz = (
            -_2q1mx * q3
            + _2q1my * q2
            + mz * q1q1
            + _2q2mx * q4
            - mz * q2q2
            + _2q3 * my * q4
            - mz * q3q3
            + mz * q4q4
        )
        _4bx = 2.0 * _2bx
        _4bz = 2.0 * _2bz

        f1 = 2.0 * (q2q4 - q1q3) - ax
        f2 = 2.0 * (q1q2 + q3q4) - ay
        f3 = 1.0 - 2.0 * (q2q2 + q3q3) - az
        f4 = _2bx * (0.5 - q3q3 - q4q4) + _2bz * (q2q4 - q1q3) - mx
        f5 = _2bx * (q2q3 - q1q4) + _2bz * (q1q2 + q3q4) - my
        f6 = _2bx * (q1q3 + q2q4) + _2bz * (0.5 - q2q2 - q3q3) - mz

        s1 = -_2q3 * f1 + _2q2 * f2 - _2bz * q3 * f4 + (-_2bx * q4 + _2bz * q2) * f5 + _2bx * q3 * f6
        s2 = _2q4 * f1 + _2q1 * f2 - 4.0 * q2 * f3 + _2bz * q4 * f4 + (_2bx * q3 + _2bz * q1) * f5 + (_2bx * q4 - _4bz * q2) * f6
        s3 = -_2q1 * f1 + _2q4 * f2 - 4.0 * q3 * f3 + (-_4bx * q3 - _2bz * q1) * f4 + (_2bx * q2 + _2bz * q4) * f5 + (_2bx * q1 - _4bz * q3) * f6
        s4 = _2q2 * f1 + _2q3 * f2 + (-_4bx * q4 + _2bz * q2) * f4 + (-_2bx * q1 + _2bz * q3) * f5 + _2bx * q2 * f6
        step = normalize(np.array([s1, s2, s3, s4]))

        q_dot = 0.5 * quat_mul(self.q, np.array([0.0, gx, gy, gz])) - self.beta * step
        self.q = normalize(self.q + q_dot * dt)
        return euler_from_quat(self.q)


def calibrate_row(row):
    raw_acc = np.array([row["ax"], row["ay"], row["az"]])
    acc = ACCEL_C @ raw_acc + ACCEL_D
    gyro = np.array([row["gx"], row["gy"], row["gz"]]) - GYRO_BIAS_DPS
    mag = MAG_MATRIX @ (np.array([row["mx"], row["my"], row["mz"]]) - MAG_BIAS)
    return acc, gyro, mag


def run_filters(rows):
    comp_alpha = 0.98
    mahony_kp = 0.08
    mahony_ki = 0.004

    def reset_state():
        return {
            "comp_initialized": False,
            "cr": 0.0,
            "cp": 0.0,
            "cy": 0.0,
            "mahony_initialized": False,
            "mr": 0.0,
            "mp": 0.0,
            "my": 0.0,
            "mi": np.zeros(3),
            "madgwick": Madgwick(beta=0.035),
        }

    state = reset_state()
    current_phase = None

    out = []
    last_t = rows[0]["t_ms"] / 1000.0
    comp_time = 0.0
    mahony_time = 0.0
    madgwick_time = 0.0
    total_start = time.perf_counter()

    for row in rows:
        if row["phase"] != current_phase:
            state = reset_state()
            current_phase = row["phase"]

        t = row["t_ms"] / 1000.0
        dt = max(1e-3, min(0.1, t - last_t))
        last_t = t
        acc, gyro, mag = calibrate_row(row)

        t0 = time.perf_counter()
        ar, ap = accel_angles(acc[0], acc[1], acc[2])
        myaw = mag_yaw(mag[0], mag[1], mag[2], ar, ap)
        if not state["comp_initialized"]:
            state["cr"], state["cp"], state["cy"] = ar, ap, myaw
            state["comp_initialized"] = True
        else:
            state["cr"] = comp_alpha * (state["cr"] + gyro[0] * dt) + (1 - comp_alpha) * ar
            state["cp"] = comp_alpha * (state["cp"] + gyro[1] * dt) + (1 - comp_alpha) * ap
            yaw_pred = state["cy"] + gyro[2] * dt
            yaw_err = wrap_deg(myaw - yaw_pred)
            state["cy"] = wrap_deg(yaw_pred + (1 - comp_alpha) * yaw_err)
        comp_time += time.perf_counter() - t0

        t0 = time.perf_counter()
        if not state["mahony_initialized"]:
            state["mr"], state["mp"], state["my"] = ar, ap, myaw
            state["mahony_initialized"] = True
        else:
            pred = np.array([
                state["mr"] + gyro[0] * dt,
                state["mp"] + gyro[1] * dt,
                wrap_deg(state["my"] + gyro[2] * dt),
            ])
            err = np.array([wrap_deg(ar - pred[0]), wrap_deg(ap - pred[1]), wrap_deg(myaw - pred[2])])
            state["mi"] += err * dt
            corrected = pred + mahony_kp * err + mahony_ki * state["mi"]
            state["mr"], state["mp"], state["my"] = corrected[0], corrected[1], wrap_deg(corrected[2])
        mahony_time += time.perf_counter() - t0

        t0 = time.perf_counter()
        madr, madp, mady = state["madgwick"].update(gyro, acc, mag, dt)
        madgwick_time += time.perf_counter() - t0

        out.append({
            "phase": row["phase"],
            "t_s": t,
            "temp_c": row["temp"],
            "comp_roll": state["cr"],
            "comp_pitch": state["cp"],
            "comp_yaw": state["cy"],
            "mahony_roll": state["mr"],
            "mahony_pitch": state["mp"],
            "mahony_yaw": state["my"],
            "madgwick_roll": madr,
            "madgwick_pitch": madp,
            "madgwick_yaw": wrap_deg(mady),
        })

    elapsed = rows[-1]["t_ms"] / 1000.0 - rows[0]["t_ms"] / 1000.0
    stats = {
        "samples": len(rows),
        "data_duration_s": elapsed,
        "sample_rate_hz": len(rows) / elapsed if elapsed > 0 else 0,
        "complementary_update_hz": len(rows) / comp_time if comp_time > 0 else 0,
        "mahony_update_hz": len(rows) / mahony_time if mahony_time > 0 else 0,
        "madgwick_update_hz": len(rows) / madgwick_time if madgwick_time > 0 else 0,
        "analysis_total_s": time.perf_counter() - total_start,
    }
    return out, stats


def alg_label(alg):
    return {
        "comp": "complementary",
        "mahony": "mahony",
        "madgwick": "madgwick",
    }[alg]


def write_outputs(timestamp, fused, update_stats):
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    fused_path = ANALYSIS_DIR / "attitude_fusion_latest.csv"
    with fused_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(fused[0].keys()))
        writer.writeheader()
        writer.writerows(fused)

    static_path = ANALYSIS_DIR / "attitude_fusion_static_std.csv"
    with static_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["phase", "algorithm", "roll_std_deg", "pitch_std_deg", "yaw_std_deg", "roll_mean_deg", "pitch_mean_deg", "yaw_mean_deg"])
        for phase in PHASES_STATIC:
            part = [r for r in fused if r["phase"] == phase]
            if not part:
                continue
            for alg in ("comp", "mahony", "madgwick"):
                vals = np.array([[r[f"{alg}_roll"], r[f"{alg}_pitch"], r[f"{alg}_yaw"]] for r in part])
                writer.writerow([
                    phase,
                    alg_label(alg),
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

    make_figures(fused)
    return fused_path, static_path, rate_path


def plot_phase(fused, phase, fig_name, title):
    part = [r for r in fused if r["phase"] == phase]
    if not part:
        return None
    t0 = part[0]["t_s"]
    t = np.array([r["t_s"] - t0 for r in part])
    fig, axes = plt.subplots(3, 1, figsize=(10, 7.2), sharex=True)
    channels = [("roll", "Roll (deg)"), ("pitch", "Pitch (deg)"), ("yaw", "Yaw (deg)")]
    colors = {"comp": "#f97316", "mahony": "#2563eb", "madgwick": "#16a34a"}
    labels = {"comp": "Complementary", "mahony": "Mahony PI", "madgwick": "Madgwick"}
    for ax, (name, ylabel) in zip(axes, channels):
        for alg in ("comp", "mahony", "madgwick"):
            ax.plot(t, [r[f"{alg}_{name}"] for r in part], label=labels[alg], color=colors[alg], linewidth=1)
        ax.set_ylabel(ylabel)
        ax.grid(True, alpha=0.25)
    axes[0].set_title(title)
    axes[-1].set_xlabel("Time (s)")
    axes[0].legend(loc="upper right", ncol=3)
    fig.tight_layout()
    path = FIG_DIR / fig_name
    fig.savefig(path, dpi=180)
    plt.close(fig)
    return path


def make_figures(fused):
    for phase, fig_name, title in PHASES_PLOT:
        plot_phase(fused, phase, fig_name, title)


def main():
    data_dir, timestamp, files = latest_timestamp_group()
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

    print("Data directory:", data_dir)
    print("Timestamp group:", timestamp)
    print("Accel calibration:", ACCEL_CAL_SOURCE)
    print("Input files:")
    for path in files:
        print(" ", path.name)
    print("Samples:", len(all_rows))
    print("Estimated sample rate: %.3f Hz" % update_stats["sample_rate_hz"])
    print("Complementary update rate: %.1f Hz" % update_stats["complementary_update_hz"])
    print("Mahony update rate: %.1f Hz" % update_stats["mahony_update_hz"])
    print("Madgwick update rate: %.1f Hz" % update_stats["madgwick_update_hz"])
    print("Wrote:", fused_path)
    print("Wrote:", static_path)
    print("Wrote:", rate_path)
    print("Figures saved to:", FIG_DIR)


if __name__ == "__main__":
    main()
