# -*- coding: utf-8 -*-
"""
15D ESKF process-noise sensitivity sweep.

Q is the process-noise covariance. Making it too small means the filter trusts
IMU prediction too much; making it too large means the estimate follows noisy GPS
too aggressively. This script reruns the same synchronized IMU+GPS log with
several Q multipliers and records innovation/smoothness metrics for the report.
"""

from pathlib import Path
import csv
import math
import statistics

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import analyze_eskf_15d_sync as eskf_sync


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ANALYSIS_DIR = PROJECT_ROOT / "data" / "analysis"
FIG_DIR = PROJECT_ROOT / "data" / "figures"
Q_SCALES = [0.01, 0.03, 0.1, 0.3, 1.0, 3.0, 10.0, 30.0, 100.0]


def finite(rows, key):
    return [r[key] for r in rows if math.isfinite(r.get(key, float("nan")))]


def pct(values, q):
    vals = sorted(v for v in values if math.isfinite(v))
    if not vals:
        return float("nan")
    idx = int(math.ceil(q * len(vals))) - 1
    return vals[max(0, min(idx, len(vals) - 1))]


def xy_step_stats(states):
    steps = []
    turns = []
    prev = None
    prev_heading = None
    for s in states:
        p = (s["e_m"], s["n_m"])
        if prev is not None:
            dx = p[0] - prev[0]
            dy = p[1] - prev[1]
            step = math.hypot(dx, dy)
            steps.append(step)
            if step > 1e-6:
                heading = math.atan2(dy, dx)
                if prev_heading is not None:
                    d = math.atan2(math.sin(heading - prev_heading), math.cos(heading - prev_heading))
                    turns.append(abs(math.degrees(d)))
                prev_heading = heading
        prev = p
    return {
        "step_std": statistics.pstdev(steps) if len(steps) > 2 else float("nan"),
        "step_p95": pct(steps, 0.95),
        "turn_p95_deg": pct(turns, 0.95),
    }


def summarize_run(q_scale, states, eskf):
    pos_innov = finite(states, "pos_innov_xy_m")
    vel_innov = finite(states, "vel_innov_xy_m")
    sig_e = finite(states, "sigma_e_m")
    sig_n = finite(states, "sigma_n_m")
    sig_v = finite(states, "sigma_ve_mps") + finite(states, "sigma_vn_mps")
    smooth = xy_step_stats(states)
    gps_rows = [s for s in states if s["gps_usable"] == 1 and math.isfinite(s["gps_lat"]) and abs(s["gps_lat"]) > 1e-9]
    gps_distance = eskf_sync.path_distance_latlon(gps_rows, "gps_lat", "gps_lon")
    eskf_distance = eskf_sync.path_distance_xy(states, "e_m", "n_m")
    pos_p95 = pct(pos_innov, 0.95)
    distance_ratio = eskf_distance / gps_distance if gps_distance > 1e-6 else float("nan")
    diverged = (
        (math.isfinite(pos_p95) and pos_p95 > 100.0)
        or (math.isfinite(distance_ratio) and distance_ratio > 5.0)
        or eskf.rejects > max(20, 0.5 * max(1, eskf.pos_updates + eskf.rejects))
    )
    return {
        "q_scale": q_scale,
        "states": len(states),
        "pos_updates": eskf.pos_updates,
        "vel_updates": eskf.vel_updates,
        "rejects": eskf.rejects,
        "gps_distance_m": gps_distance,
        "eskf_distance_m": eskf_distance,
        "distance_ratio": distance_ratio,
        "pos_innov_median_m": statistics.median(pos_innov) if pos_innov else float("nan"),
        "pos_innov_p95_m": pos_p95,
        "vel_innov_p95_mps": pct(vel_innov, 0.95),
        "mean_sigma_xy_m": statistics.mean(sig_e + sig_n) if (sig_e or sig_n) else float("nan"),
        "mean_sigma_vxy_mps": statistics.mean(sig_v) if sig_v else float("nan"),
        "step_std_m": smooth["step_std"],
        "step_p95_m": smooth["step_p95"],
        "turn_p95_deg": smooth["turn_p95_deg"],
        "final_e_m": states[-1]["e_m"] if states else float("nan"),
        "final_n_m": states[-1]["n_m"] if states else float("nan"),
        "health": "diverged" if diverged else "usable",
        "diagnosis": "check frame mapping, GPS timestamp sync, accel gravity removal and ZUPT constraints" if diverged else "Q scale is numerically usable",
    }


def save_summary(src, rows):
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = src.stem.replace("imu_gps_sync_", "")
    summary_path = ANALYSIS_DIR / ("eskf_q_sweep_summary_%s.csv" % stamp)
    fig_path = FIG_DIR / ("eskf_q_sweep_metrics_%s.png" % stamp)

    with summary_path.open("w", newline="", encoding="utf-8-sig") as f:
        keys = [
            "q_scale",
            "states",
            "pos_updates",
            "vel_updates",
            "rejects",
            "gps_distance_m",
            "eskf_distance_m",
            "distance_ratio",
            "pos_innov_median_m",
            "pos_innov_p95_m",
            "vel_innov_p95_mps",
            "mean_sigma_xy_m",
            "mean_sigma_vxy_mps",
            "step_std_m",
            "step_p95_m",
            "turn_p95_deg",
            "final_e_m",
            "final_n_m",
            "health",
            "diagnosis",
        ]
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for row in rows:
            w.writerow(row)

    x = [r["q_scale"] for r in rows]
    fig, axes = plt.subplots(2, 2, figsize=(10, 7))
    axes[0, 0].plot(x, [r["pos_innov_p95_m"] for r in rows], marker="o")
    axes[0, 0].set_ylabel("P95 position innovation (m)")
    axes[0, 1].plot(x, [r["eskf_distance_m"] for r in rows], marker="o", color="#16a34a")
    axes[0, 1].set_ylabel("Estimated path distance (m)")
    axes[1, 0].plot(x, [r["mean_sigma_xy_m"] for r in rows], marker="o", color="#f97316")
    axes[1, 0].set_ylabel("Mean sigma XY (m)")
    axes[1, 1].plot(x, [r["step_p95_m"] for r in rows], marker="o", color="#7c3aed")
    axes[1, 1].set_ylabel("P95 ENU step (m)")
    for ax in axes.ravel():
        ax.set_xscale("log")
        ax.set_xlabel("Q scale")
        ax.grid(True, alpha=0.25)
    fig.suptitle("15D ESKF process-noise Q sensitivity")
    fig.tight_layout()
    fig.savefig(fig_path, dpi=180)
    plt.close(fig)
    return summary_path, fig_path


def main():
    src = eskf_sync.latest_file(eskf_sync.SYNC_DIR, "imu_gps_sync_*.csv")
    if src is None:
        raise SystemExit("No imu_gps_sync_*.csv found in %s" % eskf_sync.SYNC_DIR)
    data = eskf_sync.read_sync_csv(src)
    rows = []
    for scale in Q_SCALES:
        states, eskf = eskf_sync.run_eskf(data, q_scale=scale)
        rows.append(summarize_run(scale, states, eskf))
        print("Q scale %g: states=%d, pos P95=%.3f m, path=%.3f m, rejects=%d, health=%s" % (
            scale,
            len(states),
            rows[-1]["pos_innov_p95_m"],
            rows[-1]["eskf_distance_m"],
            rows[-1]["rejects"],
            rows[-1]["health"],
        ))
    summary_path, fig_path = save_summary(src, rows)
    print("Source:", src)
    print("Wrote:", summary_path)
    print("Figure:", fig_path)


if __name__ == "__main__":
    main()
