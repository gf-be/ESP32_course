"""Analyze BMP280 staircase data and regenerate summary tables/figure."""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
ASSET_DIR = ROOT / "assets"
SOURCE = DATA_DIR / "staircase_esp32_0003.csv"


def r2_score(y, y_hat):
    y = np.asarray(y, dtype=float)
    y_hat = np.asarray(y_hat, dtype=float)
    ss_res = np.sum((y - y_hat) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    return 1.0 - ss_res / ss_tot


def main():
    ASSET_DIR.mkdir(exist_ok=True)
    df = pd.read_csv(SOURCE, comment="#")
    floor_means = (
        df.groupby("floor_hint", as_index=False)
        .agg(
            pressure_pa_mean=("pressure_pa", "mean"),
            pressure_pa_std=("pressure_pa", "std"),
            relative_alt_m_mean=("relative_alt_m", "mean"),
            relative_alt_m_std=("relative_alt_m", "std"),
            temp_c_mean=("temp_c", "mean"),
        )
    )
    floor_means.to_csv(DATA_DIR / "bmp280_staircase_floor_means.csv", index=False)

    floors = floor_means["floor_hint"].astype(float).to_numpy()
    pressure = floor_means["pressure_pa_mean"].astype(float).to_numpy()
    altitude = floor_means["relative_alt_m_mean"].astype(float).to_numpy()

    p_coef = np.polyfit(floors, pressure, 1)
    a_coef = np.polyfit(floors, altitude, 1)
    p_fit = np.polyval(p_coef, floors)
    a_fit = np.polyval(a_coef, floors)

    pressure_r2 = r2_score(pressure, p_fit)
    altitude_r2 = r2_score(altitude, a_fit)

    summary = pd.DataFrame(
        [
            ["source_file", SOURCE.name, "", ""],
            ["records", len(df), "rows", "floor records"],
            ["floors", "1-6", "", ""],
            ["chip_id", "0x58", "", "BMP280 expected 0x58"],
            ["pressure_slope_per_floor", p_coef[0], "Pa/floor", "expected negative"],
            ["pressure_r2", pressure_r2, "ratio", "should be > 0.98"],
            ["altitude_slope_per_floor", a_coef[0], "m/floor", "floor height estimate"],
            ["altitude_r2", altitude_r2, "ratio", ""],
            ["altitude_range", float(np.max(altitude) - np.min(altitude)), "m", ""],
        ],
        columns=["item", "value", "unit", "note"],
    )
    summary.to_csv(DATA_DIR / "bmp280_staircase_summary.csv", index=False)

    order = np.arange(len(df))
    fig, axes = plt.subplots(2, 1, figsize=(9, 7), sharex=True)
    axes[0].plot(order, df["pressure_pa"], "o-", label="raw floor records")
    axes[0].plot(np.linspace(0, len(df) - 1, len(floors)), pressure, "s--", label="floor means")
    axes[0].set_ylabel("Pressure (Pa)")
    axes[0].grid(True, alpha=0.3)
    axes[0].legend()

    axes[1].plot(order, df["relative_alt_m"], "o-", label="raw floor records")
    axes[1].plot(np.linspace(0, len(df) - 1, len(floors)), altitude, "s--", label="floor means")
    axes[1].set_ylabel("Relative altitude (m)")
    axes[1].set_xlabel("Record index")
    axes[1].grid(True, alpha=0.3)
    axes[1].legend()
    fig.suptitle(
        "BMP280 staircase test: pressure slope %.3f Pa/floor, R2 %.6f"
        % (p_coef[0], pressure_r2)
    )
    fig.tight_layout()
    fig.savefig(ASSET_DIR / "bmp280_staircase_result.png", dpi=180)
    plt.close(fig)

    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
