# -*- coding: utf-8 -*-
"""
BMP280 relative height filtering and error-budget helper.

The script reads a BMP280 pressure log, converts pressure to relative altitude,
then compares raw barometric height with a constant-velocity 1D Kalman filter.
It is intentionally offline so the same code can be used for report figures.
"""

from pathlib import Path
import csv
import math
import statistics

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
        PROJECT_ROOT / "data" / "performance",
        PROJECT_ROOT / "data" / "bmp280",
        PROJECT_ROOT / "data" / "barometer",
        LEGACY_ROOT / "data" / "bmp280",
        LEGACY_ROOT / "data" / "barometer",
        LEGACY_ROOT / "data" / "performance",
    ]
    patterns = ["*bmp280*.csv", "*baro*.csv", "*height*.csv"]
    files = []
    for folder in folders:
        if not folder.exists():
            continue
        for pattern in patterns:
            files.extend(folder.glob(pattern))
    return sorted(set(files), key=lambda p: p.stat().st_mtime, reverse=True)


def to_float(value, default=float("nan")):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except ValueError:
        return default


def read_bmp_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(line for line in f if not line.startswith("#"))
        rows = []
        for i, row in enumerate(reader):
            if not row:
                continue
            t = to_float(row.get("t_s"), default=float("nan"))
            if not math.isfinite(t):
                t_ms = to_float(row.get("t_ms"), default=float("nan"))
                t = t_ms / 1000.0 if math.isfinite(t_ms) else float(i)
            p = to_float(row.get("pressure_pa"), default=float("nan"))
            if not math.isfinite(p):
                ph = to_float(row.get("pressure_hpa"), default=float("nan"))
                p = ph * 100.0 if math.isfinite(ph) else float("nan")
            temp = to_float(row.get("temp_c"), default=to_float(row.get("temperature_c")))
            alt = to_float(row.get("relative_alt_m"), default=to_float(row.get("alt_m")))
            if math.isfinite(p):
                rows.append({"t_s": t, "pressure_pa": p, "temp_c": temp, "alt_m": alt})
    rows.sort(key=lambda r: r["t_s"])
    if len(rows) < 10:
        raise RuntimeError("Not enough BMP280 pressure rows in %s" % path)
    return rows


def pressure_to_altitude(p_pa, p0_pa):
    return 44330.0 * (1.0 - (p_pa / p0_pa) ** 0.190294957)


def build_height_series(rows):
    pressures = [r["pressure_pa"] for r in rows if math.isfinite(r["pressure_pa"])]
    p0 = statistics.median(pressures[: min(50, len(pressures))])
    out = []
    for r in rows:
        baro_h = pressure_to_altitude(r["pressure_pa"], p0)
        measured_h = r["alt_m"] if math.isfinite(r["alt_m"]) else baro_h
        out.append({
            "t_s": r["t_s"] - rows[0]["t_s"],
            "pressure_pa": r["pressure_pa"],
            "temp_c": r["temp_c"],
            "baro_h_m": baro_h,
            "measured_h_m": measured_h,
        })
    return out, p0


def estimate_dt(series):
    dts = [
        series[i]["t_s"] - series[i - 1]["t_s"]
        for i in range(1, len(series))
        if series[i]["t_s"] > series[i - 1]["t_s"]
    ]
    return statistics.median(dts) if dts else 0.2


def run_height_kf(series):
    early = series[: min(100, len(series))]
    raw_std = statistics.pstdev([r["baro_h_m"] for r in early]) if len(early) > 2 else 0.5
    sigma_z = max(0.15, raw_std)
    sigma_a = 0.45

    x = np.array([series[0]["baro_h_m"], 0.0], dtype=float)
    P = np.diag([sigma_z ** 2, 1.0])
    H = np.array([[1.0, 0.0]], dtype=float)
    R = np.array([[sigma_z ** 2]], dtype=float)

    out = []
    last_t = series[0]["t_s"]
    for row in series:
        dt = max(0.02, min(row["t_s"] - last_t, 2.0))
        last_t = row["t_s"]
        F = np.array([[1.0, dt], [0.0, 1.0]], dtype=float)
        Q = sigma_a ** 2 * np.array([[dt ** 4 / 4.0, dt ** 3 / 2.0], [dt ** 3 / 2.0, dt ** 2]], dtype=float)
        x = F @ x
        P = F @ P @ F.T + Q
        z = np.array([row["baro_h_m"]], dtype=float)
        innov = z - H @ x
        S = H @ P @ H.T + R
        K = P @ H.T @ np.linalg.inv(S)
        x = x + K @ innov
        P = (np.eye(2) - K @ H) @ P
        P = 0.5 * (P + P.T)
        out.append({**row, "kf_h_m": float(x[0]), "kf_v_mps": float(x[1]), "sigma_h_m": float(math.sqrt(max(P[0, 0], 0.0)))})
    return out, sigma_z, sigma_a


def save_outputs(src, series, p0_pa, sigma_z, sigma_a):
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    summary_path = ANALYSIS_DIR / "bmp280_height_kf_summary.csv"
    csv_path = ANALYSIS_DIR / "bmp280_height_kf_timeseries.csv"
    fig_path = FIG_DIR / "bmp280_height_kf_compare.png"

    raw = [r["baro_h_m"] for r in series]
    kf = [r["kf_h_m"] for r in series]
    residual = [a - b for a, b in zip(raw, kf)]
    temps = [r["temp_c"] for r in series if math.isfinite(r["temp_c"])]
    duration = series[-1]["t_s"] - series[0]["t_s"] if len(series) > 1 else 0.0
    dt = estimate_dt(series)

    with summary_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["item", "value", "unit", "note"])
        w.writerow(["source_file", str(src), "", ""])
        w.writerow(["samples", len(series), "rows", ""])
        w.writerow(["duration", "%.3f" % duration, "s", ""])
        w.writerow(["sample_period_median", "%.6f" % dt, "s", ""])
        w.writerow(["p0_reference", "%.3f" % p0_pa, "Pa", "median of initial pressure samples"])
        w.writerow(["raw_height_std", "%.6f" % statistics.pstdev(raw), "m", "barometer-only height spread"])
        w.writerow(["kf_height_std", "%.6f" % statistics.pstdev(kf), "m", "filtered height spread"])
        w.writerow(["raw_minus_kf_std", "%.6f" % statistics.pstdev(residual), "m", "high-frequency baro component"])
        w.writerow(["kf_sigma_z", "%.6f" % sigma_z, "m", "measurement noise estimated from initial segment"])
        w.writerow(["kf_sigma_a", "%.6f" % sigma_a, "m/s^2", "process noise for vertical acceleration model"])
        if temps:
            w.writerow(["temperature_range", "%.3f" % (max(temps) - min(temps)), "degC", "temperature cross-sensitivity indicator"])
        w.writerow(["weather_drift_rule", "8.4", "m/hPa", "pressure reference error dominates long-term absolute altitude"])

    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        keys = ["t_s", "pressure_pa", "temp_c", "baro_h_m", "kf_h_m", "kf_v_mps", "sigma_h_m"]
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for row in series:
            w.writerow({k: row.get(k, "") for k in keys})

    fig, axes = plt.subplots(2, 1, figsize=(9, 6), sharex=True)
    t = [r["t_s"] for r in series]
    axes[0].plot(t, raw, label="Barometer height", linewidth=1.0, alpha=0.75)
    axes[0].plot(t, kf, label="1D KF height", linewidth=1.7)
    axes[0].set_ylabel("Height (m)")
    axes[0].grid(True, alpha=0.25)
    axes[0].legend()
    axes[1].plot(t, [r["kf_v_mps"] for r in series], color="#16a34a", linewidth=1.2)
    axes[1].fill_between(t, [-r["sigma_h_m"] for r in series], [r["sigma_h_m"] for r in series], color="#2563eb", alpha=0.14, label="height sigma")
    axes[1].set_xlabel("Time (s)")
    axes[1].set_ylabel("Velocity / sigma")
    axes[1].grid(True, alpha=0.25)
    axes[1].legend()
    fig.suptitle("BMP280 relative height and 1D Kalman filtering")
    fig.tight_layout()
    fig.savefig(fig_path, dpi=180)
    plt.close(fig)
    return summary_path, csv_path, fig_path


def main():
    files = candidate_files()
    if not files:
        raise SystemExit("No BMP280/barometer CSV found. Put a pressure log under data/bmp280 or data/performance first.")
    src = files[0]
    rows = read_bmp_csv(src)
    height, p0_pa = build_height_series(rows)
    filtered, sigma_z, sigma_a = run_height_kf(height)
    outputs = save_outputs(src, filtered, p0_pa, sigma_z, sigma_a)
    print("Source:", src)
    print("Samples:", len(filtered), "P0=%.2f Pa" % p0_pa)
    print("Raw height std: %.4f m" % statistics.pstdev([r["baro_h_m"] for r in filtered]))
    print("KF height std: %.4f m" % statistics.pstdev([r["kf_h_m"] for r in filtered]))
    for path in outputs:
        print("Wrote:", path)


if __name__ == "__main__":
    main()
