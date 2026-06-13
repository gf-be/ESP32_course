from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def load_mag_csv(path: Path) -> np.ndarray:
    try:
        data = np.loadtxt(path, delimiter=",", skiprows=1)
        if data.size == 0:
            data = np.loadtxt(path, delimiter=",")
    except ValueError:
        data = np.loadtxt(path, delimiter=",")
    if data.ndim == 1:
        data = data.reshape(1, -1)
    if data.shape[1] >= 5:
        return data[:, 2:5]
    if data.shape[1] == 4:
        return data[:, 1:4]
    return data[:, 0:3]


def fit_ellipsoid(samples: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x, y, z = samples[:, 0], samples[:, 1], samples[:, 2]
    phi = np.column_stack(
        [
            x * x,
            y * y,
            z * z,
            2.0 * x * y,
            2.0 * x * z,
            2.0 * y * z,
            2.0 * x,
            2.0 * y,
            2.0 * z,
            np.ones_like(x),
        ]
    )

    _, singular_values, vt = np.linalg.svd(phi, full_matrices=False)
    q = vt[-1, :]

    d = np.array(
        [
            [q[0], q[3], q[4]],
            [q[3], q[1], q[5]],
            [q[4], q[5], q[2]],
        ]
    )
    p = np.array([q[6], q[7], q[8]])
    r = q[9]

    center = -np.linalg.solve(d, p)
    scale = center @ p + r
    a = -d / scale

    eigvals, eigvecs = np.linalg.eigh(a)
    if np.any(eigvals <= 0):
        raise ValueError(
            "The fitted ellipsoid is not positive definite. Recollect data with fuller 3D coverage."
        )

    sqrt_a = eigvecs @ np.diag(np.sqrt(eigvals)) @ eigvecs.T

    unit_cal = (samples - center) @ sqrt_a.T
    target_radius = float(np.median(np.linalg.norm(samples - center, axis=1)))
    w = target_radius * sqrt_a

    condition_hint = singular_values[-2] / singular_values[-1] if singular_values[-1] else np.inf
    return center, w, np.array([target_radius, condition_hint])


def set_equal_3d_axes(ax, points: np.ndarray) -> None:
    mins = points.min(axis=0)
    maxs = points.max(axis=0)
    center = (mins + maxs) / 2.0
    radius = (maxs - mins).max() / 2.0
    ax.set_xlim(center[0] - radius, center[0] + radius)
    ax.set_ylim(center[1] - radius, center[1] + radius)
    ax.set_zlim(center[2] - radius, center[2] + radius)


def print_c_arrays(center: np.ndarray, w: np.ndarray) -> None:
    print("\nPaste these values into main/main.c:\n")
    print(f"static const float MAG_C[3] = {{{center[0]:.6f}f, {center[1]:.6f}f, {center[2]:.6f}f}};")
    print("static const float MAG_W[3][3] = {")
    for row in w:
        print(f"    {{{row[0]:.8f}f, {row[1]:.8f}f, {row[2]:.8f}f}},")
    print("};")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fit HMC5883L ellipsoid calibration with DLS + SVD.")
    parser.add_argument("csv", type=Path, nargs="?", default=Path("data/mag_raw.csv"))
    parser.add_argument("-o", "--output", type=Path, default=Path("figures/mag_calib_compare.png"))
    args = parser.parse_args()

    m = load_mag_csv(args.csv)
    if len(m) < 100:
        raise SystemExit("Too few samples. Collect at least 1500 samples for the final report.")

    center, w, extra = fit_ellipsoid(m)
    m_cal = (m - center) @ w.T

    mag_before = np.linalg.norm(m, axis=1)
    mag_after = np.linalg.norm(m_cal, axis=1)
    improvement = mag_before.std() / mag_after.std()

    print(f"Samples: {len(m)}")
    print(f"Hard iron center c: {center.round(6)} uT")
    print(f"Estimated target radius: {extra[0]:.3f} uT")
    print(f"SVD separation hint: {extra[1]:.2f}")
    print(f"Before: |B| mean={mag_before.mean():.3f} uT, std={mag_before.std():.3f} uT")
    print(f"After : |B| mean={mag_after.mean():.3f} uT, std={mag_after.std():.3f} uT")
    print(f"Std improvement: {improvement:.2f}x")
    print_c_arrays(center, w)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig = plt.figure(figsize=(13, 6))

    ax1 = fig.add_subplot(121, projection="3d")
    ax1.scatter(m[:, 0], m[:, 1], m[:, 2], s=4, alpha=0.4, color="#cc4444")
    ax1.scatter([0], [0], [0], marker="+", c="black", s=120)
    ax1.set_title(f"Before calibration\n|B| std={mag_before.std():.2f} uT")
    ax1.set_xlabel("Bx (uT)")
    ax1.set_ylabel("By (uT)")
    ax1.set_zlabel("Bz (uT)")
    set_equal_3d_axes(ax1, m)

    ax2 = fig.add_subplot(122, projection="3d")
    ax2.scatter(m_cal[:, 0], m_cal[:, 1], m_cal[:, 2], s=4, alpha=0.4, color="#339966")
    ax2.scatter([0], [0], [0], marker="+", c="black", s=120)
    ax2.set_title(f"After calibration\n|B| std={mag_after.std():.2f} uT")
    ax2.set_xlabel("Bx_cal (uT)")
    ax2.set_ylabel("By_cal (uT)")
    ax2.set_zlabel("Bz_cal (uT)")
    set_equal_3d_axes(ax2, m_cal)

    fig.suptitle("HMC5883L ellipsoid calibration")
    fig.tight_layout()
    fig.savefig(args.output, dpi=180)
    print(f"Saved {args.output}")


if __name__ == "__main__":
    main()
