# -*- coding: utf-8 -*-
"""
Analyze long stationary gyro data for bias, noise and Allan deviation.

Input:
  data/gyro_allan/gyro_allan_*.csv

Output:
  data/analysis/gyro_allan_axis_stats.csv
  data/analysis/gyro_allan_summary.csv
  data/analysis/gyro_allan_deviation.csv
  data/figures/gyro_allan_timeseries.png
  data/figures/gyro_allan_histogram.png
  data/figures/gyro_allan_deviation.png
"""

from pathlib import Path
import csv
import math

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data" / "gyro_allan"
ANALYSIS_DIR = ROOT / "data" / "analysis"
FIG_DIR = ROOT / "data" / "figures"


def read_latest_csv():
    files = sorted(DATA_DIR.glob("gyro_allan_*.csv"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise FileNotFoundError("No gyro_allan_*.csv found in %s" % DATA_DIR)
    path = files[-1]
    rows = []
    meta = {}
    with path.open("r", encoding="utf-8") as f:
        content = f.readlines()
    for line in content:
        if line.startswith("#"):
            parts = line[1:].strip().split(",", 1)
            if len(parts) == 2:
                meta[parts[0]] = parts[1]
    reader = csv.DictReader(line for line in content if not line.startswith("#"))
    for row in reader:
        rows.append([
            float(row["t_ms"]),
            float(row["temp_c"]),
            float(row["gx_dps"]),
            float(row["gy_dps"]),
            float(row["gz_dps"]),
        ])
    return path, meta, np.asarray(rows, dtype=float)


def allan_deviation(rate, sample_rate_hz):
    n = len(rate)
    max_m = n // 10
    if max_m < 2:
        raise ValueError("not enough samples for Allan deviation")
    ms = np.unique(np.logspace(0, math.log10(max_m), 70).astype(int))
    taus = []
    adevs = []
    for m in ms:
        bins = n // m
        if bins < 3:
            continue
        trimmed = rate[: bins * m]
        avg = trimmed.reshape(bins, m).mean(axis=1)
        diff = np.diff(avg)
        adev = math.sqrt(0.5 * np.mean(diff * diff))
        taus.append(m / sample_rate_hz)
        adevs.append(adev)
    return np.asarray(taus), np.asarray(adevs)


def axis_stats(values):
    return {
        "mean": float(np.mean(values)),
        "std": float(np.std(values)),
        "min": float(np.min(values)),
        "max": float(np.max(values)),
        "ptp": float(np.max(values) - np.min(values)),
        "median": float(np.median(values)),
    }


def estimate_arw(taus, adev):
    mask = (taus >= 0.1) & (taus <= 10.0)
    if np.count_nonzero(mask) < 3:
        mask = np.arange(len(taus)) < min(10, len(taus))
    values = adev[mask] * np.sqrt(taus[mask])
    arw_deg_per_sqrt_s = float(np.median(values))
    arw_deg_per_sqrt_h = arw_deg_per_sqrt_s * 60.0
    return arw_deg_per_sqrt_s, arw_deg_per_sqrt_h


def save_tables(path, meta, data, allan):
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    t = data[:, 0] / 1000.0
    temp = data[:, 1]
    gyro = data[:, 2:5]
    duration_s = t[-1] - t[0]
    sample_rate = (len(t) - 1) / duration_s if duration_s > 0 else float(meta.get("sample_hz", 50))

    stats = {axis: axis_stats(gyro[:, i]) for i, axis in enumerate(("x", "y", "z"))}
    allan_metrics = {}
    for i, axis in enumerate(("x", "y", "z")):
        taus, adev = allan[axis]
        min_idx = int(np.argmin(adev))
        arw_s, arw_h = estimate_arw(taus, adev)
        allan_metrics[axis] = {
            "min_adev": float(adev[min_idx]),
            "min_tau": float(taus[min_idx]),
            "arw_deg_per_sqrt_s": arw_s,
            "arw_deg_per_sqrt_h": arw_h,
            "bias_instability_deg_per_h": float(adev[min_idx] * 3600.0),
        }

    axis_path = ANALYSIS_DIR / "gyro_allan_axis_stats.csv"
    with axis_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "axis", "bias_mean_dps", "std_dps", "min_dps", "max_dps", "peak_to_peak_dps",
            "allan_min_dps", "allan_min_tau_s", "arw_deg_per_sqrt_s", "arw_deg_per_sqrt_h",
            "bias_instability_deg_per_h",
        ])
        for axis in ("x", "y", "z"):
            s = stats[axis]
            a = allan_metrics[axis]
            writer.writerow([
                axis,
                "%.9f" % s["mean"],
                "%.9f" % s["std"],
                "%.9f" % s["min"],
                "%.9f" % s["max"],
                "%.9f" % s["ptp"],
                "%.9f" % a["min_adev"],
                "%.6f" % a["min_tau"],
                "%.9f" % a["arw_deg_per_sqrt_s"],
                "%.9f" % a["arw_deg_per_sqrt_h"],
                "%.6f" % a["bias_instability_deg_per_h"],
            ])

    summary_path = ANALYSIS_DIR / "gyro_allan_summary.csv"
    with summary_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["item", "value", "unit", "note"])
        writer.writerow(["source_file", path.name, "", "latest gyro Allan data"])
        writer.writerow(["samples", len(data), "rows", ""])
        writer.writerow(["duration", "%.3f" % duration_s, "s", ""])
        writer.writerow(["sample_rate", "%.6f" % sample_rate, "Hz", "estimated from timestamps"])
        writer.writerow(["temp_min", "%.3f" % float(np.min(temp)), "C", ""])
        writer.writerow(["temp_max", "%.3f" % float(np.max(temp)), "C", ""])
        writer.writerow(["temp_range", "%.3f" % float(np.max(temp) - np.min(temp)), "C", ""])
        for axis in ("x", "y", "z"):
            writer.writerow(["gyro_%s_bias" % axis, "%.9f" % stats[axis]["mean"], "deg/s", "stationary mean"])
            writer.writerow(["gyro_%s_std" % axis, "%.9f" % stats[axis]["std"], "deg/s", "stationary noise std"])
            writer.writerow(["gyro_%s_allan_min" % axis, "%.9f" % allan_metrics[axis]["min_adev"], "deg/s", "minimum Allan deviation"])
            writer.writerow(["gyro_%s_allan_tau" % axis, "%.6f" % allan_metrics[axis]["min_tau"], "s", "tau at minimum Allan deviation"])

    allan_path = ANALYSIS_DIR / "gyro_allan_deviation.csv"
    with allan_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["axis", "tau_s", "allan_deviation_dps"])
        for axis in ("x", "y", "z"):
            taus, adev = allan[axis]
            for tau, val in zip(taus, adev):
                writer.writerow([axis, "%.9f" % tau, "%.12f" % val])

    return axis_path, summary_path, allan_path, stats, allan_metrics, sample_rate


def make_figures(data, allan):
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    plt.rcParams["font.sans-serif"] = ["DejaVu Sans", "Arial"]
    plt.rcParams["axes.unicode_minus"] = False

    t = data[:, 0] / 1000.0
    t = t - t[0]
    temp = data[:, 1]
    gyro = data[:, 2:5]
    labels = ["gx", "gy", "gz"]
    colors = ["#ef4444", "#2563eb", "#16a34a"]

    fig, axes = plt.subplots(4, 1, figsize=(10.5, 8), sharex=True)
    for i in range(3):
        axes[i].plot(t / 60.0, gyro[:, i], color=colors[i], linewidth=0.7)
        axes[i].set_ylabel(labels[i] + " (deg/s)")
        axes[i].grid(True, alpha=0.25)
    axes[3].plot(t / 60.0, temp, color="#7c3aed", linewidth=0.8)
    axes[3].set_ylabel("Temp (C)")
    axes[3].set_xlabel("Time (min)")
    axes[3].grid(True, alpha=0.25)
    axes[0].set_title("Stationary gyro output and temperature")
    fig.tight_layout()
    timeseries_path = FIG_DIR / "gyro_allan_timeseries.png"
    fig.savefig(timeseries_path, dpi=180)
    plt.close(fig)

    fig, axes = plt.subplots(1, 3, figsize=(11, 3.6))
    for i, ax in enumerate(axes):
        ax.hist(gyro[:, i], bins=80, color=colors[i], alpha=0.75)
        ax.set_title(labels[i])
        ax.set_xlabel("deg/s")
        ax.grid(True, alpha=0.25)
    axes[0].set_ylabel("Samples")
    fig.tight_layout()
    hist_path = FIG_DIR / "gyro_allan_histogram.png"
    fig.savefig(hist_path, dpi=180)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9.2, 6.0))
    for i, axis in enumerate(("x", "y", "z")):
        taus, adev = allan[axis]
        ax.loglog(taus, adev, marker="o", markersize=3, linewidth=1.1, label=axis.upper(), color=colors[i])
        min_idx = int(np.argmin(adev))
        min_tau = float(taus[min_idx])
        min_adev = float(adev[min_idx])
        arw_s, arw_h = estimate_arw(taus, adev)
        bi_deg_h = min_adev * 3600.0
        ax.scatter([min_tau], [min_adev], s=55, color=colors[i], edgecolor="black", zorder=4)
        ax.annotate(
            "%s BI~%.2f deg/h\nARW~%.3f deg/sqrt(h)\ntau=%.1fs"
            % (axis.upper(), bi_deg_h, arw_h, min_tau),
            xy=(min_tau, min_adev),
            xytext=(12, 12 + i * 10),
            textcoords="offset points",
            fontsize=8,
            color=colors[i],
            arrowprops={"arrowstyle": "->", "color": colors[i], "lw": 0.8},
        )
    ref_tau = np.array([0.2, 20.0])
    x_taus, x_adev = allan["x"]
    arw_s, _ = estimate_arw(x_taus, x_adev)
    ref_adev = arw_s / np.sqrt(ref_tau)
    ax.loglog(ref_tau, ref_adev, "--", color="#6b7280", linewidth=1.0, label="ARW slope -1/2")
    ax.set_title("Gyroscope Allan deviation")
    ax.set_xlabel("Averaging time tau (s)")
    ax.set_ylabel("Allan deviation (deg/s)")
    ax.grid(True, which="both", alpha=0.25)
    ax.legend()
    fig.tight_layout()
    allan_path = FIG_DIR / "gyro_allan_deviation.png"
    fig.savefig(allan_path, dpi=180)
    plt.close(fig)

    return timeseries_path, hist_path, allan_path


def main():
    path, meta, data = read_latest_csv()
    sample_rate = float(meta.get("sample_hz", 50))
    gyro = data[:, 2:5]
    allan = {}
    for i, axis in enumerate(("x", "y", "z")):
        allan[axis] = allan_deviation(gyro[:, i], sample_rate)

    axis_path, summary_path, allan_path, stats, allan_metrics, estimated_rate = save_tables(path, meta, data, allan)
    figs = make_figures(data, allan)

    print("Source:", path)
    print("Samples:", len(data))
    print("Estimated sample rate: %.6f Hz" % estimated_rate)
    for axis in ("x", "y", "z"):
        s = stats[axis]
        a = allan_metrics[axis]
        print(
            "%s bias=%.6f dps std=%.6f dps min_allan=%.6f dps at tau=%.3f s ARW=%.6f deg/sqrt(h)"
            % (
                axis.upper(),
                s["mean"],
                s["std"],
                a["min_adev"],
                a["min_tau"],
                a["arw_deg_per_sqrt_h"],
            )
        )
    print("Wrote:", axis_path)
    print("Wrote:", summary_path)
    print("Wrote:", allan_path)
    for fig in figs:
        print("Figure:", fig)


if __name__ == "__main__":
    main()
