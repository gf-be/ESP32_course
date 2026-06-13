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
        data = data[:, 2:5]
    elif data.shape[1] == 4:
        data = data[:, 1:4]
    else:
        data = data[:, 0:3]
    return data


def set_equal_3d_axes(ax, points: np.ndarray) -> None:
    mins = points.min(axis=0)
    maxs = points.max(axis=0)
    center = (mins + maxs) / 2.0
    radius = (maxs - mins).max() / 2.0
    ax.set_xlim(center[0] - radius, center[0] + radius)
    ax.set_ylim(center[1] - radius, center[1] + radius)
    ax.set_zlim(center[2] - radius, center[2] + radius)


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot raw HMC5883L magnetic field samples.")
    parser.add_argument("csv", type=Path, nargs="?", default=Path("data/mag_raw.csv"))
    parser.add_argument("-o", "--output", type=Path, default=Path("figures/mag_3d_before.png"))
    args = parser.parse_args()

    m = load_mag_csv(args.csv)
    mag = np.linalg.norm(m, axis=1)
    center_est = (m.max(axis=0) + m.min(axis=0)) / 2.0

    print(f"Samples: {len(m)}")
    print(f"Bx range: {m[:,0].min():.2f} .. {m[:,0].max():.2f} uT")
    print(f"By range: {m[:,1].min():.2f} .. {m[:,1].max():.2f} uT")
    print(f"Bz range: {m[:,2].min():.2f} .. {m[:,2].max():.2f} uT")
    print(f"|B| mean={mag.mean():.2f} uT, std={mag.std():.2f} uT")
    print(f"Rough center estimate: {center_est.round(3)} uT")

    args.output.parent.mkdir(parents=True, exist_ok=True)

    fig = plt.figure(figsize=(13, 6))
    ax1 = fig.add_subplot(121, projection="3d")
    ax1.scatter(m[:, 0], m[:, 1], m[:, 2], s=4, alpha=0.45, c=mag, cmap="viridis")
    ax1.scatter([0], [0], [0], marker="+", c="red", s=120)
    ax1.set_title("Raw magnetic samples")
    ax1.set_xlabel("Bx (uT)")
    ax1.set_ylabel("By (uT)")
    ax1.set_zlabel("Bz (uT)")
    set_equal_3d_axes(ax1, m)

    ax2 = fig.add_subplot(122)
    ax2.hist(mag, bins=40, color="#5577aa", alpha=0.85)
    ax2.axvline(mag.mean(), color="#cc3333", label=f"mean={mag.mean():.2f} uT")
    ax2.set_title(f"Raw |B| distribution, std={mag.std():.2f} uT")
    ax2.set_xlabel("|B| (uT)")
    ax2.set_ylabel("Count")
    ax2.grid(alpha=0.25)
    ax2.legend()

    fig.tight_layout()
    fig.savefig(args.output, dpi=180)
    print(f"Saved {args.output}")


if __name__ == "__main__":
    main()
