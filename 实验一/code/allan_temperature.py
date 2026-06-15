#对采集到的温度数据进行 Allan 方差分析，绘制 Allan 方差 log-log 图，标注出不同噪声成分对应的斜率，从图中提取出温度传感器的零偏不稳定性和速率随机游走参数

import argparse
import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def load_temperature_csv(path: Path) -> tuple[np.ndarray, np.ndarray]:
    data = pd.read_csv(path)
    required = {"elapsed_s", "temp_c"}
    missing = required.difference(data.columns)
    if missing:
        raise ValueError(f"CSV is missing required columns: {sorted(missing)}")

    elapsed_s = data["elapsed_s"].to_numpy(dtype=float)
    temp_c = data["temp_c"].to_numpy(dtype=float)
    valid = np.isfinite(elapsed_s) & np.isfinite(temp_c)
    elapsed_s = elapsed_s[valid]
    temp_c = temp_c[valid]

    if len(temp_c) < 10:
        raise ValueError("At least 10 valid samples are required")

    return elapsed_s, temp_c


def estimate_sample_period(elapsed_s: np.ndarray) -> float:
    diffs = np.diff(elapsed_s)
    diffs = diffs[np.isfinite(diffs) & (diffs > 0)]
    if len(diffs) == 0:
        raise ValueError("Cannot estimate sample period from elapsed_s")
    return float(np.median(diffs))


def cluster_sizes(n: int) -> np.ndarray:
    max_m = max(1, n // 3)
    values = np.unique(np.logspace(0, math.log10(max_m), num=80).astype(int))
    return values[values >= 1]


def allan_deviation(values: np.ndarray, dt_s: float) -> pd.DataFrame:
    rows = []
    values = values - np.mean(values)
    n = len(values)

    for m in cluster_sizes(n):
        clusters = n // m
        if clusters < 2:
            continue

        trimmed = values[: clusters * m]
        means = trimmed.reshape(clusters, m).mean(axis=1)
        diffs = np.diff(means)
        avar = 0.5 * np.mean(diffs * diffs)
        adev = math.sqrt(float(avar))
        rows.append({"m": int(m), "tau_s": float(m * dt_s), "allan_dev_c": adev})

    result = pd.DataFrame(rows)
    if len(result) >= 3:
        log_tau = np.log10(result["tau_s"].to_numpy())
        log_adev = np.log10(result["allan_dev_c"].to_numpy())
        result["local_slope"] = np.gradient(log_adev, log_tau)
    else:
        result["local_slope"] = np.nan
    return result


def estimate_metrics(summary: pd.DataFrame, sample_count: int, dt_s: float, duration_s: float) -> str:
    min_row = summary.loc[summary["allan_dev_c"].idxmin()]
    plus_half = summary[(summary["local_slope"] >= 0.35) & (summary["local_slope"] <= 0.65)]

    lines = [
        f"sample_count: {sample_count}",
        f"sample_period_s: {dt_s:.6f}",
        f"duration_s: {duration_s:.3f}",
        f"bias_instability_proxy_c: {min_row['allan_dev_c']:.9g}",
        f"bias_instability_tau_s: {min_row['tau_s']:.9g}",
    ]

    if len(plus_half) > 0:
        coeff = np.median(plus_half["allan_dev_c"].to_numpy() / np.sqrt(plus_half["tau_s"].to_numpy()))
        gyro_style_rrw = math.sqrt(3.0) * coeff
        lines.extend(
            [
                f"random_walk_coeff_c_per_sqrt_s: {coeff:.9g}",
                f"gyro_style_rrw_coeff_c_per_sqrt_s: {gyro_style_rrw:.9g}",
                f"random_walk_tau_range_s: {plus_half['tau_s'].min():.9g}..{plus_half['tau_s'].max():.9g}",
            ]
        )
    else:
        lines.append("random_walk_coeff_c_per_sqrt_s: not_found_no_clear_plus_half_slope_region")

    return "\n".join(lines) + "\n"


def segment_statistics(elapsed_s: np.ndarray, temp_c: np.ndarray, event_start_s: float, event_end_s: float) -> pd.DataFrame:
    masks = {
        "before_heating": elapsed_s < event_start_s,
        "heating": (elapsed_s >= event_start_s) & (elapsed_s <= event_end_s),
        "after_heating": elapsed_s > event_end_s,
    }
    rows = []
    for name, mask in masks.items():
        seg_t = elapsed_s[mask]
        seg_y = temp_c[mask]
        if len(seg_y) == 0:
            rows.append({"segment": name, "samples": 0})
            continue
        rows.append(
            {
                "segment": name,
                "samples": int(len(seg_y)),
                "start_s": float(seg_t[0]),
                "end_s": float(seg_t[-1]),
                "duration_s": float(seg_t[-1] - seg_t[0]) if len(seg_t) > 1 else 0.0,
                "mean_c": float(np.mean(seg_y)),
                "median_c": float(np.median(seg_y)),
                "std_c": float(np.std(seg_y, ddof=1)) if len(seg_y) > 1 else 0.0,
                "min_c": float(np.min(seg_y)),
                "max_c": float(np.max(seg_y)),
                "range_c": float(np.max(seg_y) - np.min(seg_y)),
                "first_c": float(seg_y[0]),
                "last_c": float(seg_y[-1]),
                "delta_last_first_c": float(seg_y[-1] - seg_y[0]),
            }
        )
    return pd.DataFrame(rows)


def plot_temperature_series(
    elapsed_s: np.ndarray,
    temp_c: np.ndarray,
    out_path: Path,
    event_start_s: float | None = None,
    event_end_s: float | None = None,
) -> None:
    fig, ax = plt.subplots(figsize=(10, 5), dpi=150)
    ax.plot(elapsed_s, temp_c, linewidth=1.0, label="temperature")
    if event_start_s is not None and event_end_s is not None:
        ax.axvspan(event_start_s, event_end_s, color="tab:red", alpha=0.18, label="hot air heating")
        ax.axvline(event_start_s, color="tab:red", linewidth=0.8)
        ax.axvline(event_end_s, color="tab:red", linewidth=0.8)
    ax.set_xlabel("Elapsed time (s)")
    ax.set_ylabel("Temperature (degC)")
    ax.set_title("ESP32 Internal Temperature Time Series")
    ax.grid(True, linestyle=":", linewidth=0.6)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


def plot_segment_allan(
    elapsed_s: np.ndarray,
    temp_c: np.ndarray,
    dt_s: float,
    out_path: Path,
    event_start_s: float,
    event_end_s: float,
) -> None:
    segments = {
        "before heating": elapsed_s < event_start_s,
        "heating": (elapsed_s >= event_start_s) & (elapsed_s <= event_end_s),
        "after heating": elapsed_s > event_end_s,
    }
    fig, ax = plt.subplots(figsize=(8, 5), dpi=150)
    plotted = False
    for name, mask in segments.items():
        values = temp_c[mask]
        if len(values) < 30:
            continue
        summary = allan_deviation(values, dt_s)
        if len(summary) == 0:
            continue
        ax.loglog(
            summary["tau_s"].to_numpy(),
            summary["allan_dev_c"].to_numpy(),
            marker="o",
            markersize=2.5,
            linewidth=1.0,
            label=name,
        )
        plotted = True

    ax.set_xlabel("Averaging time tau (s)")
    ax.set_ylabel("Allan deviation (degC)")
    ax.set_title("Segmented Allan Deviation")
    ax.grid(True, which="both", linestyle=":", linewidth=0.6)
    if plotted:
        ax.legend()
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


def add_reference_slope(ax, tau: np.ndarray, adev: np.ndarray, slope: float, label: str, scale: float) -> None:
    x0 = tau[len(tau) // 4]
    y0 = np.interp(np.log10(x0), np.log10(tau), np.log10(adev))
    y0 = 10**y0 * scale
    x = np.array([tau[0], tau[-1]])
    y = y0 * (x / x0) ** slope
    ax.plot(x, y, "--", linewidth=1.0, label=label)


def plot_allan(summary: pd.DataFrame, out_path: Path) -> None:
    tau = summary["tau_s"].to_numpy()
    adev = summary["allan_dev_c"].to_numpy()

    fig, ax = plt.subplots(figsize=(8, 5), dpi=150)
    ax.loglog(tau, adev, marker="o", markersize=3, linewidth=1.2, label="temperature Allan deviation")
    add_reference_slope(ax, tau, adev, -0.5, "slope -1/2 white noise", 2.0)
    add_reference_slope(ax, tau, adev, 0.0, "slope 0 bias instability", 1.2)
    add_reference_slope(ax, tau, adev, 0.5, "slope +1/2 random walk", 0.7)

    ax.set_xlabel("Averaging time tau (s)")
    ax.set_ylabel("Allan deviation (degC)")
    ax.set_title("ESP32 Internal Temperature Allan Deviation")
    ax.grid(True, which="both", linestyle=":", linewidth=0.6)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


def parse_args():
    parser = argparse.ArgumentParser(description="Analyze ESP32 temperature CSV with Allan deviation.")
    parser.add_argument("csv", type=Path, help="CSV with elapsed_s and temp_c columns")
    parser.add_argument("--out-dir", type=Path, default=Path("experiment1_prep/outputs"))
    parser.add_argument("--event-start-s", type=float, help="Optional event start time in elapsed seconds")
    parser.add_argument("--event-end-s", type=float, help="Optional event end time in elapsed seconds")
    return parser.parse_args()


def main():
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    elapsed_s, temp_c = load_temperature_csv(args.csv)
    dt_s = estimate_sample_period(elapsed_s)
    duration_s = float(elapsed_s[-1] - elapsed_s[0])
    summary = allan_deviation(temp_c, dt_s)

    summary_path = args.out_dir / "allan_temperature_summary.csv"
    metrics_path = args.out_dir / "allan_temperature_metrics.txt"
    plot_path = args.out_dir / "allan_temperature.png"
    time_plot_path = args.out_dir / "temperature_time_series.png"

    summary.to_csv(summary_path, index=False)
    metrics_path.write_text(estimate_metrics(summary, len(temp_c), dt_s, duration_s), encoding="utf-8")
    plot_allan(summary, plot_path)
    plot_temperature_series(elapsed_s, temp_c, time_plot_path, args.event_start_s, args.event_end_s)

    if args.event_start_s is not None and args.event_end_s is not None:
        stats_path = args.out_dir / "temperature_event_segments.csv"
        segment_plot_path = args.out_dir / "allan_temperature_segments.png"
        stats = segment_statistics(elapsed_s, temp_c, args.event_start_s, args.event_end_s)
        stats.to_csv(stats_path, index=False)
        plot_segment_allan(elapsed_s, temp_c, dt_s, segment_plot_path, args.event_start_s, args.event_end_s)
        print(f"Wrote {stats_path}")
        print(f"Wrote {segment_plot_path}")

    print(f"Wrote {summary_path}")
    print(f"Wrote {metrics_path}")
    print(f"Wrote {plot_path}")
    print(f"Wrote {time_plot_path}")


if __name__ == "__main__":
    main()
