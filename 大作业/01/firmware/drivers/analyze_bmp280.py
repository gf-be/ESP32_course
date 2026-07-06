# -*- coding: utf-8 -*-
"""
Analyze BMP280 pressure/temperature experiment data.

Input:
  data/bmp280/bmp280_static_*.csv
  data/bmp280/bmp280_height_change_*.csv

Output:
  data/analysis/bmp280_summary.csv
  data/analysis/bmp280_static_stats.csv
  data/figures/bmp280_static_pressure_temp.png
  data/figures/bmp280_height_change.png
"""

from pathlib import Path
import csv
import statistics

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data" / "bmp280"
ANALYSIS_DIR = ROOT / "data" / "analysis"
FIG_DIR = ROOT / "data" / "figures"


def latest_pair():
    static_files = sorted(DATA_DIR.glob("bmp280_static_*.csv"), key=lambda p: p.stat().st_mtime)
    motion_files = sorted(DATA_DIR.glob("bmp280_height_change_*.csv"), key=lambda p: p.stat().st_mtime)
    if not static_files:
        raise FileNotFoundError("No bmp280_static_*.csv found in %s" % DATA_DIR)
    if not motion_files:
        raise FileNotFoundError("No bmp280_height_change_*.csv found in %s" % DATA_DIR)
    return static_files[-1], motion_files[-1]


def read_csv(path):
    meta = {}
    rows = []
    with path.open("r", encoding="utf-8") as f:
        lines = f.readlines()
    for line in lines:
        if line.startswith("#"):
            parts = line[1:].strip().split(",", 1)
            if len(parts) == 2:
                meta[parts[0]] = parts[1]
    reader = csv.DictReader(line for line in lines if not line.startswith("#"))
    for row in reader:
        rows.append({
            "t_s": float(row["t_ms"]) / 1000.0,
            "label": row["label"],
            "temp_c": float(row["temp_c"]),
            "pressure_pa": float(row["pressure_pa"]),
            "pressure_hpa": float(row["pressure_hpa"]),
            "relative_alt_m": float(row["relative_alt_m"]),
        })
    return meta, rows


def stats(values):
    return {
        "mean": statistics.fmean(values),
        "std": statistics.pstdev(values),
        "min": min(values),
        "max": max(values),
        "ptp": max(values) - min(values),
    }


def save_tables(static_path, motion_path, static_meta, static_rows, motion_meta, motion_rows):
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    p_stats = stats([r["pressure_pa"] for r in static_rows])
    t_stats = stats([r["temp_c"] for r in static_rows])
    a_stats = stats([r["relative_alt_m"] for r in static_rows])
    motion_alt = [r["relative_alt_m"] for r in motion_rows]
    motion_pressure = [r["pressure_pa"] for r in motion_rows]

    static_stats_path = ANALYSIS_DIR / "bmp280_static_stats.csv"
    with static_stats_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["item", "mean", "std", "min", "max", "peak_to_peak", "unit"])
        writer.writerow(["pressure", "%.6f" % p_stats["mean"], "%.6f" % p_stats["std"], "%.6f" % p_stats["min"], "%.6f" % p_stats["max"], "%.6f" % p_stats["ptp"], "Pa"])
        writer.writerow(["temperature", "%.6f" % t_stats["mean"], "%.6f" % t_stats["std"], "%.6f" % t_stats["min"], "%.6f" % t_stats["max"], "%.6f" % t_stats["ptp"], "C"])
        writer.writerow(["relative_altitude", "%.6f" % a_stats["mean"], "%.6f" % a_stats["std"], "%.6f" % a_stats["min"], "%.6f" % a_stats["max"], "%.6f" % a_stats["ptp"], "m"])

    summary_path = ANALYSIS_DIR / "bmp280_summary.csv"
    with summary_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["item", "value", "unit", "note"])
        writer.writerow(["static_source_file", static_path.name, "", ""])
        writer.writerow(["motion_source_file", motion_path.name, "", ""])
        writer.writerow(["chip_id", static_meta.get("chip_id", ""), "", "BMP280 normally 0x58"])
        writer.writerow(["static_samples", len(static_rows), "rows", ""])
        writer.writerow(["motion_samples", len(motion_rows), "rows", ""])
        writer.writerow(["static_pressure_std", "%.6f" % p_stats["std"], "Pa", "smaller is better"])
        writer.writerow(["static_temperature_std", "%.6f" % t_stats["std"], "C", ""])
        writer.writerow(["static_altitude_std", "%.6f" % a_stats["std"], "m", "computed from pressure"])
        writer.writerow(["motion_altitude_min", "%.6f" % min(motion_alt), "m", ""])
        writer.writerow(["motion_altitude_max", "%.6f" % max(motion_alt), "m", ""])
        writer.writerow(["motion_altitude_range", "%.6f" % (max(motion_alt) - min(motion_alt)), "m", ""])
        writer.writerow(["motion_pressure_range", "%.6f" % (max(motion_pressure) - min(motion_pressure)), "Pa", ""])

    return static_stats_path, summary_path


def make_figures(static_rows, motion_rows):
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    plt.rcParams["font.sans-serif"] = ["DejaVu Sans", "Arial"]
    plt.rcParams["axes.unicode_minus"] = False

    t = [r["t_s"] for r in static_rows]
    p = [r["pressure_hpa"] for r in static_rows]
    temp = [r["temp_c"] for r in static_rows]
    alt = [r["relative_alt_m"] for r in static_rows]

    fig, axes = plt.subplots(3, 1, figsize=(9, 7), sharex=True)
    axes[0].plot(t, p, color="#2563eb")
    axes[0].set_ylabel("Pressure (hPa)")
    axes[1].plot(t, temp, color="#f97316")
    axes[1].set_ylabel("Temp (C)")
    axes[2].plot(t, alt, color="#16a34a")
    axes[2].set_ylabel("Rel. alt (m)")
    axes[2].set_xlabel("Time (s)")
    axes[0].set_title("BMP280 static pressure/temperature noise")
    for ax in axes:
        ax.grid(True, alpha=0.25)
    fig.tight_layout()
    static_fig = FIG_DIR / "bmp280_static_pressure_temp.png"
    fig.savefig(static_fig, dpi=180)
    plt.close(fig)

    t = [r["t_s"] for r in motion_rows]
    p = [r["pressure_hpa"] for r in motion_rows]
    temp = [r["temp_c"] for r in motion_rows]
    alt = [r["relative_alt_m"] for r in motion_rows]

    fig, axes = plt.subplots(3, 1, figsize=(9, 7), sharex=True)
    axes[0].plot(t, alt, color="#16a34a")
    axes[0].set_ylabel("Rel. alt (m)")
    axes[1].plot(t, p, color="#2563eb")
    axes[1].set_ylabel("Pressure (hPa)")
    axes[2].plot(t, temp, color="#f97316")
    axes[2].set_ylabel("Temp (C)")
    axes[2].set_xlabel("Time (s)")
    axes[0].set_title("BMP280 height-change experiment")
    for ax in axes:
        ax.grid(True, alpha=0.25)
    fig.tight_layout()
    motion_fig = FIG_DIR / "bmp280_height_change.png"
    fig.savefig(motion_fig, dpi=180)
    plt.close(fig)

    return static_fig, motion_fig


def main():
    static_path, motion_path = latest_pair()
    static_meta, static_rows = read_csv(static_path)
    motion_meta, motion_rows = read_csv(motion_path)
    static_stats_path, summary_path = save_tables(static_path, motion_path, static_meta, static_rows, motion_meta, motion_rows)
    figs = make_figures(static_rows, motion_rows)

    print("Static source:", static_path)
    print("Motion source:", motion_path)
    print("Static samples:", len(static_rows))
    print("Motion samples:", len(motion_rows))
    print("Wrote:", static_stats_path)
    print("Wrote:", summary_path)
    for fig in figs:
        print("Figure:", fig)


if __name__ == "__main__":
    main()
