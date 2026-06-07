"""Step 4 PC side: folium map + matplotlib statistics."""

import argparse
import json
from pathlib import Path

import folium
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def load_track(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    rename_map = {
        "num_sat": "sats",
        "fix_quality": "quality",
        "lat_deg": "lat",
        "lon_deg": "lon",
        "alt_m": "alt",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
    for col in ("lat", "lon", "quality", "sats", "hdop", "alt", "elapsed_ms"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def build_summary(df: pd.DataFrame) -> dict:
    valid = df[(df["quality"] > 0) & df["lat"].notna() & df["lon"].notna()].copy()
    return {
        "samples": int(len(df)),
        "valid_samples": int(len(valid)),
        "valid_rate_percent": round(100.0 * len(valid) / max(len(df), 1), 2),
        "avg_hdop": float(valid["hdop"].mean()) if len(valid) else None,
        "avg_sats": float(valid["sats"].mean()) if len(valid) else None,
        "min_sats": int(valid["sats"].min()) if len(valid) else None,
        "max_sats": int(valid["sats"].max()) if len(valid) else None,
        "lat_mean": float(valid["lat"].mean()) if len(valid) else None,
        "lon_mean": float(valid["lon"].mean()) if len(valid) else None,
    }


def plot_folium(df: pd.DataFrame, out_html: Path) -> None:
    valid = df[(df["quality"] > 0) & df["lat"].notna() & df["lon"].notna()].copy()
    if valid.empty:
        raise ValueError("no valid GNSS fixes found; collect data outdoors until quality > 0")
    center_lat = valid["lat"].mean()
    center_lon = valid["lon"].mean()
    m = folium.Map(location=[center_lat, center_lon], zoom_start=18, tiles="OpenStreetMap")

    points = list(zip(valid["lat"], valid["lon"]))
    folium.PolyLine(points, color="red", weight=2, opacity=0.8).add_to(m)
    folium.Marker(points[0], popup="Start", icon=folium.Icon(color="green")).add_to(m)
    folium.Marker(points[-1], popup="End", icon=folium.Icon(color="red")).add_to(m)

    for _, row in valid.iterrows():
        color = "green" if row["hdop"] < 1.5 else ("orange" if row["hdop"] < 3 else "red")
        folium.CircleMarker(
            location=(row["lat"], row["lon"]),
            radius=2,
            color=color,
            fill=True,
            fill_opacity=0.6,
            popup="Sats: %s, HDOP: %.1f" % (row["sats"], row["hdop"]),
        ).add_to(m)

    m.save(str(out_html))


def plot_time_series(df: pd.DataFrame, assets_dir: Path) -> None:
    valid = df[(df["quality"] > 0)].copy()
    if valid.empty:
        raise ValueError("no valid GNSS fixes found; cannot plot statistics")
    if "elapsed_ms" in valid.columns:
        t_min = valid["elapsed_ms"] / 60000.0
    else:
        t_min = np.arange(len(valid))

    fig, ax1 = plt.subplots(figsize=(9, 4), dpi=150)
    ax1.plot(t_min, valid["hdop"], label="HDOP", color="#1f77b4")
    ax1.set_xlabel("Elapsed time (min)")
    ax1.set_ylabel("HDOP")
    ax2 = ax1.twinx()
    ax2.plot(t_min, valid["sats"], label="Satellites", color="#ff7f0e", alpha=0.8)
    ax2.set_ylabel("Satellite count")
    ax1.set_title("HDOP and satellite count vs time")
    ax1.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(assets_dir / "hdop_satellite_time_series.png")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 4), dpi=150)
    ax.hist(valid["sats"].dropna(), bins=20, edgecolor="white")
    ax.set_xlabel("Satellite count")
    ax.set_ylabel("Samples")
    ax.set_title("Satellite count distribution")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(assets_dir / "satellite_count_distribution.png")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--track", required=True, help="track csv from receiver or shell")
    parser.add_argument("--out-dir", default="data")
    parser.add_argument("--assets-dir", default="assets")
    args = parser.parse_args()

    track_path = Path(args.track)
    out_dir = Path(args.out_dir)
    assets_dir = Path(args.assets_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)

    df = load_track(track_path)
    if df.empty:
        raise ValueError("track CSV is empty: %s" % track_path)
    summary = build_summary(df)
    summary_path = out_dir / "track_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    plot_folium(df, out_dir / "track.html")
    plot_time_series(df, assets_dir)

    print("Wrote %s" % (out_dir / "track.html"))
    print("Wrote %s" % summary_path)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
