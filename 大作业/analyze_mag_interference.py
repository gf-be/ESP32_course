"""
Quick magnetometer interference check for data from pc_mag_rotate_capture.py.

Run this file on the computer. It reads the latest mag_rotate CSV, estimates
hard-iron center by min/max, reports axis ranges and radius spread, and writes a
summary CSV for the report.
"""

from pathlib import Path
import csv
import math
import statistics


def read_latest_csv(data_dir):
    files = sorted(data_dir.glob("mag_rotate_*.csv"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise FileNotFoundError("No mag_rotate_*.csv found in %s" % data_dir)
    path = files[-1]
    rows = []
    with path.open("r", encoding="utf-8") as f:
        reader = csv.reader(line for line in f if not line.startswith("#"))
        header = next(reader)
        idx = {name: header.index(name) for name in ("mx_raw", "my_raw", "mz_raw")}
        for row in reader:
            if row:
                rows.append((float(row[idx["mx_raw"]]), float(row[idx["my_raw"]]), float(row[idx["mz_raw"]])))
    return path, rows


def main():
    root = Path(__file__).resolve().parent
    data_dir = root / "data" / "mag_rotate"
    out_dir = root / "data" / "analysis"
    out_dir.mkdir(parents=True, exist_ok=True)

    path, rows = read_latest_csv(data_dir)
    xs = [r[0] for r in rows]
    ys = [r[1] for r in rows]
    zs = [r[2] for r in rows]

    mins = [min(xs), min(ys), min(zs)]
    maxs = [max(xs), max(ys), max(zs)]
    centers = [(a + b) / 2.0 for a, b in zip(mins, maxs)]
    ranges = [b - a for a, b in zip(mins, maxs)]
    half_ranges = [r / 2.0 for r in ranges]

    corrected = [
        (x - centers[0], y - centers[1], z - centers[2])
        for x, y, z in rows
    ]
    radii = [math.sqrt(x * x + y * y + z * z) for x, y, z in corrected]
    radius_mean = statistics.fmean(radii)
    radius_std = statistics.pstdev(radii)
    radius_cv = radius_std / radius_mean if radius_mean else float("nan")

    range_mean = statistics.fmean(half_ranges)
    axis_imbalance = max(half_ranges) / min(half_ranges) if min(half_ranges) else float("inf")

    summary_path = out_dir / "mag_interference_summary.csv"
    with summary_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["item", "value", "unit", "note"])
        writer.writerow(["source_file", path.name, "", "latest mag rotation data"])
        writer.writerow(["samples", len(rows), "rows", ""])
        writer.writerow(["hard_iron_x", "%.3f" % centers[0], "raw count", "min/max center estimate"])
        writer.writerow(["hard_iron_y", "%.3f" % centers[1], "raw count", "min/max center estimate"])
        writer.writerow(["hard_iron_z", "%.3f" % centers[2], "raw count", "min/max center estimate"])
        writer.writerow(["half_range_x", "%.3f" % half_ranges[0], "raw count", ""])
        writer.writerow(["half_range_y", "%.3f" % half_ranges[1], "raw count", ""])
        writer.writerow(["half_range_z", "%.3f" % half_ranges[2], "raw count", ""])
        writer.writerow(["mean_half_range", "%.3f" % range_mean, "raw count", ""])
        writer.writerow(["axis_imbalance", "%.3f" % axis_imbalance, "ratio", "larger means stronger soft-iron/coverage issue"])
        writer.writerow(["radius_mean_after_centering", "%.3f" % radius_mean, "raw count", ""])
        writer.writerow(["radius_std_after_centering", "%.3f" % radius_std, "raw count", ""])
        writer.writerow(["radius_cv_after_centering", "%.4f" % radius_cv, "ratio", "smaller is better"])

    print("Source:", path)
    print("Samples:", len(rows))
    print("Estimated hard-iron center: x=%.1f, y=%.1f, z=%.1f raw counts" % tuple(centers))
    print("Axis half-ranges: x=%.1f, y=%.1f, z=%.1f raw counts" % tuple(half_ranges))
    print("Axis imbalance ratio: %.3f" % axis_imbalance)
    print("Centered radius mean/std/CV: %.1f / %.1f / %.4f" % (radius_mean, radius_std, radius_cv))
    print("")
    if axis_imbalance > 1.8 or radius_cv > 0.35:
        print("Result: magnetic data looks strongly distorted or rotation coverage is insufficient.")
        print("Repeat away from metal/laptop/phone, and rotate through more complete 3D orientations.")
    elif axis_imbalance > 1.3 or radius_cv > 0.20:
        print("Result: moderate distortion. Usable for report, but ellipsoid calibration is recommended.")
    else:
        print("Result: data looks reasonably balanced for a first calibration run.")
    print("Wrote:", summary_path)


if __name__ == "__main__":
    main()
