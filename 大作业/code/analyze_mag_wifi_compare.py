"""
Analyze WiFi off/on magnetometer comparison data.

Run this file on the computer after pc_mag_wifi_compare_capture.py. It reads the
latest paired CSV files in data/mag_wifi_compare, writes summary CSV/JSON files,
and generates report-ready figures.
"""

from pathlib import Path
import csv
import json
import math
import statistics

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def read_csv(path):
    rows = []
    with path.open("r", encoding="utf-8") as f:
        reader = csv.reader(line for line in f if not line.startswith("#") and line.strip())
        header = next(reader)
        idx = {name: header.index(name) for name in header}
        for row in reader:
            rows.append({
                "t_s": float(row[idx["t_ms"]]) / 1000.0,
                "mx": float(row[idx["mx_raw"]]),
                "my": float(row[idx["my_raw"]]),
                "mz": float(row[idx["mz_raw"]]),
                "scan_count": float(row[idx["wifi_scan_count"]]),
            })
    return rows


def latest_pair(data_dir):
    off_files = sorted(data_dir.glob("mag_wifi_off_*.csv"), key=lambda p: p.stat().st_mtime)
    if not off_files:
        raise FileNotFoundError("No mag_wifi_off_*.csv files found in %s" % data_dir)
    off = off_files[-1]
    stamp = off.stem.replace("mag_wifi_off_", "")
    on = data_dir / ("mag_wifi_on_scan_%s.csv" % stamp)
    if not on.exists():
        on_files = sorted(data_dir.glob("mag_wifi_on_scan_*.csv"), key=lambda p: p.stat().st_mtime)
        if not on_files:
            raise FileNotFoundError("No mag_wifi_on_scan_*.csv files found in %s" % data_dir)
        on = on_files[-1]
    return off, on


def stats(rows):
    axes = {
        "x": [r["mx"] for r in rows],
        "y": [r["my"] for r in rows],
        "z": [r["mz"] for r in rows],
    }
    norm = [math.sqrt(r["mx"] ** 2 + r["my"] ** 2 + r["mz"] ** 2) for r in rows]
    result = {
        "samples": len(rows),
        "duration_s": rows[-1]["t_s"] - rows[0]["t_s"] if len(rows) > 1 else 0.0,
        "scan_count_last": rows[-1]["scan_count"] if rows else 0,
        "norm_mean": statistics.fmean(norm),
        "norm_std": statistics.pstdev(norm),
    }
    for axis, values in axes.items():
        result["m%s_mean" % axis] = statistics.fmean(values)
        result["m%s_std" % axis] = statistics.pstdev(values)
        result["m%s_min" % axis] = min(values)
        result["m%s_max" % axis] = max(values)
    return result


def main():
    root = Path(__file__).resolve().parent
    data_dir = root / "data" / "mag_wifi_compare"
    out_dir = root / "data" / "analysis"
    fig_dir = root / "data" / "figures"
    out_dir.mkdir(parents=True, exist_ok=True)
    fig_dir.mkdir(parents=True, exist_ok=True)

    off_path, on_path = latest_pair(data_dir)
    off_rows = read_csv(off_path)
    on_rows = read_csv(on_path)
    off = stats(off_rows)
    on = stats(on_rows)

    delta = {
        "dx": on["mx_mean"] - off["mx_mean"],
        "dy": on["my_mean"] - off["my_mean"],
        "dz": on["mz_mean"] - off["mz_mean"],
        "dnorm": on["norm_mean"] - off["norm_mean"],
        "std_ratio_x": on["mx_std"] / off["mx_std"] if off["mx_std"] else float("inf"),
        "std_ratio_y": on["my_std"] / off["my_std"] if off["my_std"] else float("inf"),
        "std_ratio_z": on["mz_std"] / off["mz_std"] if off["mz_std"] else float("inf"),
        "norm_std_ratio": on["norm_std"] / off["norm_std"] if off["norm_std"] else float("inf"),
    }
    delta["vector_shift"] = math.sqrt(delta["dx"] ** 2 + delta["dy"] ** 2 + delta["dz"] ** 2)
    baseline_norm = off["norm_mean"] if off["norm_mean"] else float("nan")
    delta["vector_shift_percent_of_field"] = delta["vector_shift"] / baseline_norm * 100.0

    result = {
        "wifi_off_file": off_path.name,
        "wifi_on_file": on_path.name,
        "wifi_off": off,
        "wifi_on_scan": on,
        "delta_on_minus_off": delta,
    }

    json_path = out_dir / "mag_wifi_compare_summary.json"
    csv_path = out_dir / "mag_wifi_compare_summary.csv"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["item", "wifi_off", "wifi_on_scan", "delta_or_ratio", "unit", "note"])
        writer.writerow(["source_file", off_path.name, on_path.name, "", "", "latest paired capture"])
        writer.writerow(["samples", off["samples"], on["samples"], "", "rows", ""])
        writer.writerow(["duration", "%.3f" % off["duration_s"], "%.3f" % on["duration_s"], "", "s", ""])
        writer.writerow(["wifi_scan_count", off["scan_count_last"], on["scan_count_last"], "", "times", "WiFi-on condition scans APs repeatedly"])
        for axis in "xyz":
            writer.writerow([
                "m%s_mean" % axis,
                "%.3f" % off["m%s_mean" % axis],
                "%.3f" % on["m%s_mean" % axis],
                "%.3f" % delta["d%s" % axis],
                "raw count",
                "mean shift after WiFi enabled",
            ])
            writer.writerow([
                "m%s_std" % axis,
                "%.3f" % off["m%s_std" % axis],
                "%.3f" % on["m%s_std" % axis],
                "%.3f" % delta["std_ratio_%s" % axis],
                "ratio",
                "std ratio, WiFi on/off",
            ])
        writer.writerow(["norm_mean", "%.3f" % off["norm_mean"], "%.3f" % on["norm_mean"], "%.3f" % delta["dnorm"], "raw count", "field magnitude shift"])
        writer.writerow(["norm_std", "%.3f" % off["norm_std"], "%.3f" % on["norm_std"], "%.3f" % delta["norm_std_ratio"], "ratio", "magnitude std ratio"])
        writer.writerow(["vector_shift", "", "", "%.3f" % delta["vector_shift"], "raw count", "3-axis mean vector shift"])
        writer.writerow(["vector_shift_percent_of_field", "", "", "%.3f" % delta["vector_shift_percent_of_field"], "%", "shift relative to WiFi-off mean field magnitude"])

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, axs = plt.subplots(3, 1, figsize=(10, 7), sharex=True)
    colors = {"x": "#2563eb", "y": "#16a34a", "z": "#dc2626"}
    for ax, axis in zip(axs, "xyz"):
        ax.plot([r["t_s"] for r in off_rows], [r["m" + axis] for r in off_rows], label="WiFi off", linewidth=0.8, color=colors[axis])
        ax.plot([r["t_s"] for r in on_rows], [r["m" + axis] for r in on_rows], label="WiFi on scan", linewidth=0.8, color="#111827", alpha=0.75)
        ax.set_ylabel("M%s raw" % axis.upper())
        ax.grid(True, alpha=0.3)
        ax.legend(ncol=2)
    axs[0].set_title("Magnetometer WiFi off/on stationary comparison")
    axs[-1].set_xlabel("Time (s)")
    fig.tight_layout()
    fig.savefig(fig_dir / "mag_wifi_compare_timeseries.png", dpi=180)
    plt.close(fig)

    labels = ["Mx", "My", "Mz", "|M|"]
    off_means = [off["mx_mean"], off["my_mean"], off["mz_mean"], off["norm_mean"]]
    on_means = [on["mx_mean"], on["my_mean"], on["mz_mean"], on["norm_mean"]]
    x = range(len(labels))
    width = 0.36
    fig, axs = plt.subplots(1, 2, figsize=(11, 4))
    axs[0].bar([i - width / 2 for i in x], off_means, width=width, label="WiFi off", color="#2563eb")
    axs[0].bar([i + width / 2 for i in x], on_means, width=width, label="WiFi on scan", color="#f97316")
    axs[0].set_xticks(list(x), labels)
    axs[0].set_ylabel("raw count")
    axs[0].set_title("Mean magnetic field comparison")
    axs[0].grid(True, axis="y", alpha=0.25)
    axs[0].legend()

    shifts = [delta["dx"], delta["dy"], delta["dz"], delta["dnorm"]]
    axs[1].bar(labels, shifts, color=["#2563eb", "#16a34a", "#dc2626", "#7c3aed"])
    axs[1].axhline(0, color="black", linewidth=0.8)
    axs[1].set_ylabel("raw count")
    axs[1].set_title("WiFi on - WiFi off mean shift")
    axs[1].grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(fig_dir / "mag_wifi_compare_shift.png", dpi=180)
    plt.close(fig)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("Wrote:", csv_path)
    print("Wrote:", json_path)
    print("Wrote:", fig_dir / "mag_wifi_compare_timeseries.png")
    print("Wrote:", fig_dir / "mag_wifi_compare_shift.png")


if __name__ == "__main__":
    main()
