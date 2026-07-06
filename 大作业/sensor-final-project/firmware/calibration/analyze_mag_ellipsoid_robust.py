# -*- coding: utf-8 -*-
"""
Robust HMC5883L ellipsoid calibration check.

This script keeps the ordinary SVD ellipsoid fit as the baseline, then rejects
outliers with a median/MAD radius rule and refits the ellipsoid. It gives the
report a concrete answer to: "what happens if a phone or metal object disturbs
some samples?"
"""

from pathlib import Path
import csv
import math

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LEGACY_ROOT = PROJECT_ROOT.parent
ANALYSIS_DIR = PROJECT_ROOT / "data" / "analysis"
FIG_DIR = PROJECT_ROOT / "data" / "figures"


def candidate_files():
    folders = [
        PROJECT_ROOT / "data" / "calibration",
        PROJECT_ROOT / "data" / "mag_ellipsoid",
        LEGACY_ROOT / "data" / "mag_ellipsoid",
    ]
    files = []
    for folder in folders:
        if folder.exists():
            files.extend(folder.glob("mag_ellipsoid_*.csv"))
    return sorted(set(files), key=lambda p: p.stat().st_mtime, reverse=True)


def read_mag_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(line for line in f if not line.startswith("#"))
        rows = []
        for row in reader:
            if not row:
                continue
            try:
                rows.append([
                    float(row.get("t_ms", row.get("t_s", len(rows)))),
                    float(row.get("mx_raw", row.get("mx", row.get("mag_x")))),
                    float(row.get("my_raw", row.get("my", row.get("mag_y")))),
                    float(row.get("mz_raw", row.get("mz", row.get("mag_z")))),
                ])
            except (TypeError, ValueError):
                continue
    if len(rows) < 30:
        raise RuntimeError("Not enough magnetometer rows in %s" % path)
    return np.asarray(rows, dtype=float)


def fit_ellipsoid(points):
    x, y, z = points[:, 0], points[:, 1], points[:, 2]
    D = np.column_stack([
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
    _, s, vt = np.linalg.svd(D, full_matrices=False)
    q = vt[-1, :]

    A = np.array([
        [q[0], q[3], q[4]],
        [q[3], q[1], q[5]],
        [q[4], q[5], q[2]],
    ], dtype=float)
    b = np.array([q[6], q[7], q[8]], dtype=float)
    c = float(q[9])

    if np.linalg.det(A) < 0:
        A, b, c = -A, -b, -c
    center = -np.linalg.solve(A, b)
    scale = float(center @ A @ center - c)
    if scale <= 0:
        A, b, c = -A, -b, -c
        center = -np.linalg.solve(A, b)
        scale = float(center @ A @ center - c)
    if scale <= 0:
        raise RuntimeError("Invalid ellipsoid scale; collect a fuller 3D rotation data set")

    shape = A / scale
    eigvals, eigvecs = np.linalg.eigh(shape)
    if np.any(eigvals <= 0):
        raise RuntimeError("Invalid ellipsoid eigenvalues; check data coverage/outliers")
    radii = 1.0 / np.sqrt(eigvals)
    target_radius = float(np.mean(radii))
    transform = eigvecs @ np.diag(target_radius * np.sqrt(eigvals)) @ eigvecs.T
    corrected = (transform @ (points - center).T).T
    cond = float(s[0] / max(s[-1], 1e-12))
    return center, radii, target_radius, transform, corrected, cond


def radius_stats(points, center=None):
    shifted = points if center is None else points - center
    r = np.linalg.norm(shifted, axis=1)
    return {
        "mean": float(np.mean(r)),
        "std": float(np.std(r, ddof=1)),
        "cv": float(np.std(r, ddof=1) / np.mean(r)),
        "median": float(np.median(r)),
        "p95_abs_residual": float(np.percentile(np.abs(r - np.median(r)), 95)),
    }


def robust_refit(points):
    base = fit_ellipsoid(points)
    corrected = base[4]
    radii = np.linalg.norm(corrected, axis=1)
    median = float(np.median(radii))
    mad = float(np.median(np.abs(radii - median)))
    sigma = 1.4826 * mad if mad > 1e-9 else float(np.std(radii, ddof=1))
    gate = max(3.5 * sigma, 0.08 * median)
    inlier_mask = np.abs(radii - median) <= gate
    if int(np.count_nonzero(inlier_mask)) < 30:
        inlier_mask[:] = True
    robust = fit_ellipsoid(points[inlier_mask])
    corrected_all = (robust[3] @ (points - robust[0]).T).T
    return base, robust, corrected_all, inlier_mask, gate


def save_outputs(src, rows, base, robust, corrected_all, mask, gate):
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    points = rows[:, 1:4]
    base_corrected = base[4]

    raw_stats = radius_stats(points, (points.min(axis=0) + points.max(axis=0)) / 2.0)
    base_stats = radius_stats(base_corrected)
    robust_stats = radius_stats(corrected_all)
    improvement = raw_stats["cv"] / robust_stats["cv"] if robust_stats["cv"] > 0 else float("nan")

    summary_path = ANALYSIS_DIR / "mag_ellipsoid_robust_summary.csv"
    with summary_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["item", "value", "unit", "note"])
        w.writerow(["source_file", str(src), "", ""])
        w.writerow(["samples_total", len(points), "rows", ""])
        w.writerow(["samples_inlier", int(np.count_nonzero(mask)), "rows", "MAD radius gate"])
        w.writerow(["samples_outlier", int(len(mask) - np.count_nonzero(mask)), "rows", "rejected before refit"])
        w.writerow(["outlier_ratio", "%.6f" % (1.0 - np.mean(mask)), "ratio", "larger means stronger local interference"])
        w.writerow(["mad_gate", "%.6f" % gate, "raw count", "absolute radius residual gate"])
        w.writerow(["svd_condition_baseline", "%.6e" % base[5], "ratio", "large value means ill-conditioned data coverage"])
        w.writerow(["svd_condition_robust", "%.6e" % robust[5], "ratio", "after outlier rejection"])
        for name, center in [("baseline", base[0]), ("robust", robust[0])]:
            w.writerow([name + "_hard_iron_x", "%.6f" % center[0], "raw count", "ellipsoid center"])
            w.writerow([name + "_hard_iron_y", "%.6f" % center[1], "raw count", "ellipsoid center"])
            w.writerow([name + "_hard_iron_z", "%.6f" % center[2], "raw count", "ellipsoid center"])
        w.writerow(["raw_radius_cv", "%.6f" % raw_stats["cv"], "ratio", "before calibration"])
        w.writerow(["baseline_cal_radius_cv", "%.6f" % base_stats["cv"], "ratio", "ordinary SVD"])
        w.writerow(["robust_cal_radius_cv", "%.6f" % robust_stats["cv"], "ratio", "MAD-refit SVD"])
        w.writerow(["robust_cv_improvement", "%.6f" % improvement, "ratio", "raw CV / robust calibrated CV"])
        w.writerow(["axis_imbalance_robust", "%.6f" % (max(robust[1]) / min(robust[1])), "ratio", "soft-iron indicator"])

    corrected_path = ANALYSIS_DIR / "mag_ellipsoid_robust_corrected_latest.csv"
    with corrected_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["t_ms", "mx_raw", "my_raw", "mz_raw", "mx_cal", "my_cal", "mz_cal", "inlier"])
        for src_row, cal, ok in zip(rows, corrected_all, mask):
            w.writerow([
                "%.0f" % src_row[0],
                "%.0f" % src_row[1],
                "%.0f" % src_row[2],
                "%.0f" % src_row[3],
                "%.6f" % cal[0],
                "%.6f" % cal[1],
                "%.6f" % cal[2],
                int(bool(ok)),
            ])

    raw_r = np.linalg.norm(points - ((points.min(axis=0) + points.max(axis=0)) / 2.0), axis=1)
    base_r = np.linalg.norm(base_corrected, axis=1)
    robust_r = np.linalg.norm(corrected_all, axis=1)
    fig, ax = plt.subplots(figsize=(9, 4.8))
    ax.hist(raw_r, bins=45, alpha=0.45, label="Raw centered", color="#f97316")
    ax.hist(base_r, bins=45, alpha=0.55, label="Ordinary SVD", color="#64748b")
    ax.hist(robust_r, bins=45, alpha=0.55, label="Robust refit", color="#2563eb")
    ax.set_title("Magnetometer radius spread: raw vs SVD vs robust refit")
    ax.set_xlabel("Radius (raw count)")
    ax.set_ylabel("Samples")
    ax.grid(True, alpha=0.25)
    ax.legend()
    ax.text(
        0.02,
        0.96,
        "CV %.4f -> %.4f, outliers %.1f%%"
        % (raw_stats["cv"], robust_stats["cv"], 100.0 * (1.0 - np.mean(mask))),
        transform=ax.transAxes,
        va="top",
    )
    fig.tight_layout()
    hist_path = FIG_DIR / "mag_ellipsoid_robust_radius_compare.png"
    fig.savefig(hist_path, dpi=180)
    plt.close(fig)

    fig = plt.figure(figsize=(10, 4.8))
    ax1 = fig.add_subplot(121, projection="3d")
    ax2 = fig.add_subplot(122, projection="3d")
    ax1.scatter(points[mask, 0], points[mask, 1], points[mask, 2], s=3, alpha=0.35, color="#2563eb", label="inlier")
    if np.any(~mask):
        ax1.scatter(points[~mask, 0], points[~mask, 1], points[~mask, 2], s=8, alpha=0.8, color="#ef4444", label="outlier")
    ax2.scatter(corrected_all[:, 0], corrected_all[:, 1], corrected_all[:, 2], s=3, alpha=0.35, color="#16a34a")
    ax1.set_title("Raw cloud with robust outlier marks")
    ax2.set_title("Robust calibrated cloud")
    for ax in (ax1, ax2):
        ax.set_xlabel("X")
        ax.set_ylabel("Y")
        ax.set_zlabel("Z")
    ax1.legend(loc="upper left")
    fig.tight_layout()
    cloud_path = FIG_DIR / "mag_ellipsoid_robust_3d.png"
    fig.savefig(cloud_path, dpi=180)
    plt.close(fig)

    return summary_path, corrected_path, hist_path, cloud_path


def main():
    files = candidate_files()
    if not files:
        raise SystemExit("No mag_ellipsoid_*.csv found under project/legacy data folders")
    src = files[0]
    rows = read_mag_csv(src)
    base, robust, corrected, mask, gate = robust_refit(rows[:, 1:4])
    outputs = save_outputs(src, rows, base, robust, corrected, mask, gate)
    print("Source:", src)
    print("Samples total/inlier/outlier:", len(rows), int(np.count_nonzero(mask)), int(len(mask) - np.count_nonzero(mask)))
    print("Robust hard-iron center: %.3f, %.3f, %.3f raw counts" % tuple(robust[0]))
    print("Robust axis imbalance: %.3f" % (max(robust[1]) / min(robust[1])))
    for path in outputs:
        print("Wrote:", path)


if __name__ == "__main__":
    main()
