"""Compare GNSS quality between outdoor and indoor/shielded environments."""

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


def summarize(path: Path, label: str) -> dict:
    df = pd.read_csv(path)
    for col in ("quality", "lat", "lon", "hdop", "sats"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    valid = df[(df["quality"] > 0) & df["lat"].notna() & df["lon"].notna()]
    return {
        "label": label,
        "file": str(path),
        "samples": int(len(df)),
        "valid_samples": int(len(valid)),
        "valid_rate_percent": round(100 * len(valid) / max(len(df), 1), 2),
        "avg_hdop_valid": round(float(valid["hdop"].mean()), 3) if len(valid) else None,
        "avg_sats_valid": round(float(valid["sats"].mean()), 3) if len(valid) else None,
        "invalid_samples": int(len(df) - len(valid)),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--outdoor", default="data/track_flash_outdoor_001.csv")
    parser.add_argument("--indoor", default="data/track_20260605_212206.csv")
    parser.add_argument("--out-json", default="data/indoor_outdoor_quality_summary.json")
    parser.add_argument("--out-fig", default="assets/indoor_outdoor_quality_compare.png")
    args = parser.parse_args()

    summaries = [
        summarize(Path(args.outdoor), "Outdoor route"),
        summarize(Path(args.indoor), "Indoor short test"),
    ]
    Path(args.out_json).write_text(json.dumps(summaries, indent=2, ensure_ascii=False), encoding="utf-8")

    labels = [s["label"] for s in summaries]
    valid_rates = [s["valid_rate_percent"] for s in summaries]
    hdop = [s["avg_hdop_valid"] or 0 for s in summaries]
    sats = [s["avg_sats_valid"] or 0 for s in summaries]

    fig, axes = plt.subplots(1, 3, figsize=(10, 3.6), dpi=150)
    axes[0].bar(labels, valid_rates, color=["#16a34a", "#dc2626"])
    axes[0].set_title("Valid fix rate")
    axes[0].set_ylabel("%")
    axes[0].set_ylim(0, 100)

    axes[1].bar(labels, hdop, color=["#16a34a", "#dc2626"])
    axes[1].set_title("Average HDOP")

    axes[2].bar(labels, sats, color=["#16a34a", "#dc2626"])
    axes[2].set_title("Average satellites")

    for ax in axes:
        ax.tick_params(axis="x", labelrotation=18)
        ax.grid(True, axis="y", alpha=0.3)

    fig.tight_layout()
    fig.savefig(args.out_fig)
    plt.close(fig)

    print(json.dumps(summaries, indent=2, ensure_ascii=False))
    print("Wrote %s" % args.out_json)
    print("Wrote %s" % args.out_fig)


if __name__ == "__main__":
    main()
