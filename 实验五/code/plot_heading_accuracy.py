from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def circular_error(measured: np.ndarray, truth: np.ndarray) -> np.ndarray:
    err = np.abs(measured - truth) % 360.0
    return np.minimum(err, 360.0 - err)


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot raw/calibrated heading accuracy.")
    parser.add_argument("csv", type=Path, nargs="?", default=Path("data/heading_12_points.csv"))
    parser.add_argument("-o", "--output", type=Path, default=Path("figures/heading_accuracy.png"))
    args = parser.parse_args()

    rows = []
    with args.csv.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(
                [
                    float(row["true_deg"]),
                    float(row["yaw_raw_deg"]),
                    float(row["yaw_cal_deg"]),
                ]
            )

    data = np.asarray(rows, dtype=float)
    truth = data[:, 0]
    raw = data[:, 1]
    cal = data[:, 2]
    err_raw = circular_error(raw, truth)
    err_cal = circular_error(cal, truth)

    print(f"Raw heading error: mean={err_raw.mean():.2f} deg, max={err_raw.max():.2f} deg")
    print(f"Cal heading error: mean={err_cal.mean():.2f} deg, max={err_cal.max():.2f} deg")

    theta_truth = np.deg2rad(truth)
    theta_raw = np.deg2rad(raw)
    theta_cal = np.deg2rad(cal)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig = plt.figure(figsize=(12, 5.8))

    ax1 = fig.add_subplot(121, projection="polar")
    ax1.plot(theta_truth, np.ones_like(theta_truth) * 1.15, "ko-", label="Reference")
    ax1.plot(theta_raw, np.ones_like(theta_raw) * 1.0, "ro-", label="Raw")
    ax1.plot(theta_cal, np.ones_like(theta_cal) * 0.85, "go-", label="Calibrated")
    ax1.set_yticklabels([])
    ax1.set_title("Heading comparison")
    ax1.legend(loc="lower left", bbox_to_anchor=(-0.15, -0.15))

    ax2 = fig.add_subplot(122)
    x = np.arange(len(truth))
    ax2.bar(x - 0.18, err_raw, width=0.36, label="Raw", color="#cc5555")
    ax2.bar(x + 0.18, err_cal, width=0.36, label="Calibrated", color="#44aa77")
    ax2.set_xticks(x)
    ax2.set_xticklabels([f"{int(v)}" for v in truth], rotation=45)
    ax2.set_xlabel("Reference heading (deg)")
    ax2.set_ylabel("Absolute circular error (deg)")
    ax2.grid(axis="y", alpha=0.25)
    ax2.legend()
    ax2.set_title("Heading error")

    fig.tight_layout()
    fig.savefig(args.output, dpi=180)
    print(f"Saved {args.output}")


if __name__ == "__main__":
    main()
