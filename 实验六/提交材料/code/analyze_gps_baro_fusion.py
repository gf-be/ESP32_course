"""Analyze GPS/BMP280 complementary altitude fusion data."""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
ASSET_DIR = ROOT / "assets"
SOURCE = DATA_DIR / "gps_baro_0005.csv"
ALPHA = 0.98


def main():
    ASSET_DIR.mkdir(exist_ok=True)
    df = pd.read_csv(SOURCE, comment="#")
    t = (df["t_ms"].astype(float) - float(df["t_ms"].iloc[0])) / 1000.0
    gps_alt = pd.to_numeric(df["gps_alt_m"], errors="coerce")
    gps_valid = (df["gps_valid"].astype(int) == 1) & gps_alt.notna()
    baro_alt = pd.to_numeric(df["baro_alt_m"], errors="coerce")

    first_gps_alt = gps_alt[gps_valid].iloc[0] if gps_valid.any() else np.nan
    gps_relative = gps_alt - first_gps_alt
    corrected_fused = baro_alt.copy()
    corrected_fused[gps_valid] = ALPHA * baro_alt[gps_valid] + (1.0 - ALPHA) * gps_relative[gps_valid]

    satellites = pd.to_numeric(df["satellites"], errors="coerce")
    hdop = pd.to_numeric(df["hdop"], errors="coerce").replace(-1, np.nan)

    def pop_std(series):
        return float(np.nanstd(np.asarray(series, dtype=float), ddof=0))

    summary = pd.DataFrame(
        [
            ["source_file", SOURCE.name, "", ""],
            ["samples", len(df), "", ""],
            ["duration_s", float(t.iloc[-1] - t.iloc[0]), "s", ""],
            ["gps_valid_samples", int(gps_valid.sum()), "", ""],
            ["gps_valid_duration_s", float(t[gps_valid].iloc[-1] - t[gps_valid].iloc[0]) if gps_valid.any() else 0.0, "s", ""],
            ["satellites_mean", float(satellites[gps_valid].mean()), "", ""],
            ["satellites_max", int(satellites[gps_valid].max()), "", ""],
            ["hdop_mean", float(hdop[gps_valid].mean()), "", ""],
            ["gps_alt_mean_m", float(gps_alt[gps_valid].mean()), "m", ""],
            ["gps_alt_std_m", pop_std(gps_alt[gps_valid]), "m", ""],
            ["gps_relative_alt_std_m", pop_std(gps_relative[gps_valid]), "m", ""],
            ["baro_alt_std_on_gps_valid_m", pop_std(baro_alt[gps_valid]), "m", ""],
            ["corrected_fused_alt_std_m", pop_std(corrected_fused[gps_valid]), "m", ""],
            ["baro_alt_range_m", float(baro_alt.max() - baro_alt.min()), "m", ""],
            ["note", "corrected_fused uses GPS relative altitude: gps_alt - first_valid_gps_alt", "", ""],
        ],
        columns=["item", "value", "unit", "note"],
    )
    summary.to_csv(DATA_DIR / "gps_baro_fusion_summary.csv", index=False)

    fig, ax = plt.subplots(figsize=(10, 5.8))
    ax.plot(t, baro_alt, label="BMP280 relative altitude", linewidth=1.4)
    ax.plot(t[gps_valid], gps_relative[gps_valid], label="GPS relative altitude", linewidth=1.0, alpha=0.75)
    ax.plot(t, corrected_fused, label="Corrected complementary fusion", linewidth=1.6)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Relative altitude (m)")
    ax.set_title("GPS/barometric complementary altitude fusion")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(ASSET_DIR / "gps_baro_fusion_height_corrected.png", dpi=180)
    plt.close(fig)

    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
