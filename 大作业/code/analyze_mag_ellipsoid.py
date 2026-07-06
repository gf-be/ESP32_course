# -*- coding: utf-8 -*-
"""
Analyze HMC5883L magnetometer ellipsoid calibration data.

Input: data/mag_ellipsoid/mag_ellipsoid_*.csv
Output:
  data/analysis/mag_ellipsoid_summary.csv
  data/analysis/mag_ellipsoid_calibration_matrix.csv
  data/analysis/mag_ellipsoid_corrected_latest.csv
  data/figures/mag_ellipsoid_*.png
"""

from pathlib import Path
import csv
import math

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data" / "mag_ellipsoid"
ANALYSIS_DIR = ROOT / "data" / "analysis"
FIG_DIR = ROOT / "data" / "figures"


def read_latest_csv():
    files = sorted(DATA_DIR.glob("mag_ellipsoid_*.csv"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise FileNotFoundError("No mag_ellipsoid_*.csv found in %s" % DATA_DIR)
    path = files[-1]
    rows = []
    with path.open("r", encoding="utf-8") as f:
        reader = csv.reader(line for line in f if not line.startswith("#"))
        header = next(reader)
        idx = {name: header.index(name) for name in ("t_ms", "mx_raw", "my_raw", "mz_raw")}
        for row in reader:
            if not row:
                continue
            rows.append([
                float(row[idx["t_ms"]]),
                float(row[idx["mx_raw"]]),
                float(row[idx["my_raw"]]),
                float(row[idx["mz_raw"]]),
            ])
    return path, np.asarray(rows, dtype=float)


def fit_ellipsoid(points):
    x = points[:, 0]
    y = points[:, 1]
    z = points[:, 2]
    design = np.column_stack([
        x * x,
        y * y,
        z * z,
        2 * x * y,
        2 * x * z,
        2 * y * z,
        2 * x,
        2 * y,
        2 * z,
        np.ones_like(x),
    ])
    _, _, vt = np.linalg.svd(design, full_matrices=False)
    coeff = vt[-1, :]
    if coeff[-1] > 0:
        coeff = -coeff

    quad = np.array([
        [coeff[0], coeff[3], coeff[4]],
        [coeff[3], coeff[1], coeff[5]],
        [coeff[4], coeff[5], coeff[2]],
    ])
    linear = np.array([coeff[6], coeff[7], coeff[8]])
    constant = coeff[9]

    center = -np.linalg.solve(quad, linear)
    scale = float(center @ quad @ center - constant)
    shape = quad / scale
    eigvals, eigvecs = np.linalg.eigh(shape)
    if np.any(eigvals <= 0):
        raise RuntimeError("Fitted ellipsoid is not positive definite. Please repeat the 3D rotation capture.")

    radii = 1.0 / np.sqrt(eigvals)
    target_radius = float(np.mean(radii))
    sqrt_shape = eigvecs @ np.diag(np.sqrt(eigvals)) @ eigvecs.T
    transform = target_radius * sqrt_shape
    corrected = (points - center) @ transform.T
    return center, radii, target_radius, transform, corrected


def radius_stats(points, center=None):
    if center is None:
        center = np.mean(points, axis=0)
    centered = points - center
    radii = np.linalg.norm(centered, axis=1)
    return {
        "mean": float(np.mean(radii)),
        "std": float(np.std(radii)),
        "cv": float(np.std(radii) / np.mean(radii)),
        "min": float(np.min(radii)),
        "max": float(np.max(radii)),
    }


def minmax_center(points):
    return (np.min(points, axis=0) + np.max(points, axis=0)) / 2.0


def save_summary(path, rows, center, ellipsoid_radii, target_radius, raw_stats, cal_stats, transform):
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = ANALYSIS_DIR / "mag_ellipsoid_summary.csv"
    with summary_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["item", "value", "unit", "note"])
        writer.writerow(["source_file", path.name, "", "latest mag ellipsoid data"])
        writer.writerow(["samples", len(rows), "rows", ""])
        writer.writerow(["hard_iron_x", "%.6f" % center[0], "raw count", "ellipsoid center"])
        writer.writerow(["hard_iron_y", "%.6f" % center[1], "raw count", "ellipsoid center"])
        writer.writerow(["hard_iron_z", "%.6f" % center[2], "raw count", "ellipsoid center"])
        writer.writerow(["ellipsoid_radius_1", "%.6f" % ellipsoid_radii[0], "raw count", "principal radius"])
        writer.writerow(["ellipsoid_radius_2", "%.6f" % ellipsoid_radii[1], "raw count", "principal radius"])
        writer.writerow(["ellipsoid_radius_3", "%.6f" % ellipsoid_radii[2], "raw count", "principal radius"])
        writer.writerow(["axis_imbalance", "%.6f" % (max(ellipsoid_radii) / min(ellipsoid_radii)), "ratio", "larger means stronger soft-iron"])
        writer.writerow(["target_radius", "%.6f" % target_radius, "raw count", "mean principal radius"])
        writer.writerow(["raw_radius_mean", "%.6f" % raw_stats["mean"], "raw count", "before calibration"])
        writer.writerow(["raw_radius_std", "%.6f" % raw_stats["std"], "raw count", "before calibration"])
        writer.writerow(["raw_radius_cv", "%.6f" % raw_stats["cv"], "ratio", "before calibration"])
        writer.writerow(["cal_radius_mean", "%.6f" % cal_stats["mean"], "raw count", "after calibration"])
        writer.writerow(["cal_radius_std", "%.6f" % cal_stats["std"], "raw count", "after calibration"])
        writer.writerow(["cal_radius_cv", "%.6f" % cal_stats["cv"], "ratio", "after calibration"])
        writer.writerow(["cv_improvement", "%.6f" % (raw_stats["cv"] / cal_stats["cv"]), "ratio", "raw CV / calibrated CV"])

    matrix_path = ANALYSIS_DIR / "mag_ellipsoid_calibration_matrix.csv"
    with matrix_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["row", "m0", "m1", "m2"])
        for i in range(3):
            writer.writerow([i, "%.10f" % transform[i, 0], "%.10f" % transform[i, 1], "%.10f" % transform[i, 2]])

    return summary_path, matrix_path


def save_corrected(path, rows, corrected):
    out_path = ANALYSIS_DIR / "mag_ellipsoid_corrected_latest.csv"
    with out_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["source_file", path.name])
        writer.writerow(["t_ms", "mx_raw", "my_raw", "mz_raw", "mx_cal", "my_cal", "mz_cal"])
        for src, cal in zip(rows, corrected):
            writer.writerow([
                "%.0f" % src[0],
                "%.0f" % src[1],
                "%.0f" % src[2],
                "%.0f" % src[3],
                "%.6f" % cal[0],
                "%.6f" % cal[1],
                "%.6f" % cal[2],
            ])
    return out_path


def make_figures(points, corrected, raw_stats, cal_stats):
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    plt.rcParams["font.sans-serif"] = ["DejaVu Sans", "Arial"]
    plt.rcParams["axes.unicode_minus"] = False

    fig = plt.figure(figsize=(10, 4.8))
    ax1 = fig.add_subplot(121, projection="3d")
    ax2 = fig.add_subplot(122, projection="3d")
    ax1.scatter(points[:, 0], points[:, 1], points[:, 2], s=3, alpha=0.35, color="#f97316")
    ax2.scatter(corrected[:, 0], corrected[:, 1], corrected[:, 2], s=3, alpha=0.35, color="#2563eb")
    ax1.set_title("Raw magnetometer cloud")
    ax2.set_title("Calibrated magnetometer cloud")
    for ax in (ax1, ax2):
        ax.set_xlabel("X")
        ax.set_ylabel("Y")
        ax.set_zlabel("Z")
    fig.tight_layout()
    cloud_path = FIG_DIR / "mag_ellipsoid_3d_before_after.png"
    fig.savefig(cloud_path, dpi=180)
    plt.close(fig)

    pairs = [(0, 1, "XY"), (0, 2, "XZ"), (1, 2, "YZ")]
    fig, axes = plt.subplots(2, 3, figsize=(11, 6.5))
    for col, (a, b, title) in enumerate(pairs):
        axes[0, col].scatter(points[:, a], points[:, b], s=3, alpha=0.35, color="#f97316")
        axes[1, col].scatter(corrected[:, a], corrected[:, b], s=3, alpha=0.35, color="#2563eb")
        axes[0, col].set_title("Raw " + title)
        axes[1, col].set_title("Calibrated " + title)
        axes[0, col].axis("equal")
        axes[1, col].axis("equal")
        axes[0, col].grid(True, alpha=0.25)
        axes[1, col].grid(True, alpha=0.25)
    fig.tight_layout()
    proj_path = FIG_DIR / "mag_ellipsoid_projection_before_after.png"
    fig.savefig(proj_path, dpi=180)
    plt.close(fig)

    raw_r = np.linalg.norm(points - minmax_center(points), axis=1)
    cal_r = np.linalg.norm(corrected, axis=1)
    fig, ax = plt.subplots(figsize=(8.8, 4.8))
    ax.hist(raw_r, bins=45, alpha=0.65, label="Raw centered radius", color="#f97316")
    ax.hist(cal_r, bins=45, alpha=0.65, label="Calibrated radius", color="#2563eb")
    ax.set_title("Radius spread before and after calibration")
    ax.set_xlabel("Radius (raw count)")
    ax.set_ylabel("Samples")
    ax.legend()
    ax.grid(True, alpha=0.25)
    text = "CV: %.4f -> %.4f" % (raw_stats["cv"], cal_stats["cv"])
    ax.text(0.02, 0.95, text, transform=ax.transAxes, va="top")
    fig.tight_layout()
    radius_path = FIG_DIR / "mag_ellipsoid_radius_hist.png"
    fig.savefig(radius_path, dpi=180)
    plt.close(fig)

    return cloud_path, proj_path, radius_path


def main():
    path, rows = read_latest_csv()
    points = rows[:, 1:4]
    center, radii, target_radius, transform, corrected = fit_ellipsoid(points)
    raw_stats = radius_stats(points, minmax_center(points))
    cal_stats = radius_stats(corrected, np.zeros(3))

    summary_path, matrix_path = save_summary(path, rows, center, radii, target_radius, raw_stats, cal_stats, transform)
    corrected_path = save_corrected(path, rows, corrected)
    figures = make_figures(points, corrected, raw_stats, cal_stats)

    print("Source:", path)
    print("Samples:", len(rows))
    print("Hard-iron center: x=%.3f, y=%.3f, z=%.3f raw counts" % tuple(center))
    print("Ellipsoid principal radii: %.3f, %.3f, %.3f raw counts" % tuple(radii))
    print("Axis imbalance: %.3f" % (max(radii) / min(radii)))
    print("Radius CV before/after: %.4f -> %.4f" % (raw_stats["cv"], cal_stats["cv"]))
    print("CV improvement: %.2f x" % (raw_stats["cv"] / cal_stats["cv"]))
    print("Wrote:", summary_path)
    print("Wrote:", matrix_path)
    print("Wrote:", corrected_path)
    for fig in figures:
        print("Figure:", fig)


if __name__ == "__main__":
    main()
