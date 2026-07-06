# -*- coding: utf-8 -*-
"""
AI denoising experiment for IMU six-channel data.

Input channels:
  ax, ay, az, gx, gy, gz

Compared methods:
  raw signal
  low-pass filter
  first-order Kalman filter
  1D-CNN denoiser

The script uses stationary IMU data to build self-supervised training samples:
the noisy window is the input, and a zero-phase moving average is used as the
pseudo-clean target. Metrics are computed against the stationary channel mean.
"""

from pathlib import Path
import csv
import math
import time

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data" / "gyro_allan"
ANALYSIS_DIR = ROOT / "data" / "analysis"
FIG_DIR = ROOT / "data" / "figures"

CHANNELS = ["ax_g", "ay_g", "az_g", "gx_dps", "gy_dps", "gz_dps"]
ACC_CHANNELS = ["ax_g", "ay_g", "az_g"]
GYRO_CHANNELS = ["gx_dps", "gy_dps", "gz_dps"]

WINDOW = 64
STRIDE = 4
EPOCHS = 18
BATCH_SIZE = 256
LEARNING_RATE = 1e-3
LOWPASS_ALPHA = 0.08
MOVING_AVG = 41


def read_latest_csv():
    files = sorted(DATA_DIR.glob("gyro_allan_*.csv"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise FileNotFoundError("No gyro_allan_*.csv found in %s" % DATA_DIR)
    path = files[-1]
    rows = []
    meta = {}
    with path.open("r", encoding="utf-8") as f:
        lines = f.readlines()
    for line in lines:
        if line.startswith("#"):
            parts = line[1:].strip().split(",", 1)
            if len(parts) == 2:
                meta[parts[0]] = parts[1]
    reader = csv.DictReader(line for line in lines if not line.startswith("#"))
    for row in reader:
        rows.append([
            float(row["t_ms"]),
            float(row["ax_g"]),
            float(row["ay_g"]),
            float(row["az_g"]),
            float(row["gx_dps"]),
            float(row["gy_dps"]),
            float(row["gz_dps"]),
        ])
    return path, meta, np.asarray(rows, dtype=np.float32)


def moving_average_zero_phase(x, size):
    if size % 2 == 0:
        size += 1
    pad = size // 2
    kernel = np.ones(size, dtype=np.float32) / size
    out = np.zeros_like(x)
    for i in range(x.shape[1]):
        padded = np.pad(x[:, i], (pad, pad), mode="edge")
        out[:, i] = np.convolve(padded, kernel, mode="valid")
    return out


def lowpass_iir(x, alpha):
    out = np.zeros_like(x)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = alpha * x[i] + (1.0 - alpha) * out[i - 1]
    return out


def kalman_1d_channel(z, q=1e-5, r=None):
    if r is None:
        r = float(np.var(z[: min(len(z), 2000)])) * 0.2 + 1e-8
    x = float(z[0])
    p = 1.0
    out = np.zeros_like(z)
    for i, value in enumerate(z):
        p = p + q
        k = p / (p + r)
        x = x + k * (float(value) - x)
        p = (1.0 - k) * p
        out[i] = x
    return out


def kalman_filter(x):
    out = np.zeros_like(x)
    for i in range(x.shape[1]):
        q = 1e-7 if i < 3 else 1e-5
        out[:, i] = kalman_1d_channel(x[:, i], q=q)
    return out


def make_windows(x, y, window, stride):
    half = window // 2
    xs = []
    ys = []
    centers = []
    for center in range(half, len(x) - half, stride):
        xs.append(x[center - half:center + half])
        ys.append(y[center])
        centers.append(center)
    return np.asarray(xs, dtype=np.float32), np.asarray(ys, dtype=np.float32), np.asarray(centers, dtype=np.int64)


class CNN1DDenoiser(nn.Module):
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv1d(6, 32, kernel_size=5, padding=2),
            nn.ReLU(),
            nn.Conv1d(32, 32, kernel_size=5, padding=2),
            nn.ReLU(),
            nn.Conv1d(32, 16, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.AdaptiveAvgPool1d(1),
        )
        self.head = nn.Linear(16, 6)

    def forward(self, x):
        x = x.transpose(1, 2)
        x = self.net(x).squeeze(-1)
        return self.head(x)


def train_cnn(x, target):
    clean = moving_average_zero_phase(target, MOVING_AVG)
    wins, labels, centers = make_windows(x, clean, WINDOW, STRIDE)

    split = int(len(wins) * 0.8)
    x_mean = wins[:split].mean(axis=(0, 1), keepdims=True)
    x_std = wins[:split].std(axis=(0, 1), keepdims=True) + 1e-8
    y_mean = labels[:split].mean(axis=0, keepdims=True)
    y_std = labels[:split].std(axis=0, keepdims=True) + 1e-8

    wins_n = (wins - x_mean) / x_std
    labels_n = (labels - y_mean) / y_std

    train_ds = TensorDataset(torch.from_numpy(wins_n[:split]), torch.from_numpy(labels_n[:split]))
    val_x = torch.from_numpy(wins_n[split:])
    val_y = torch.from_numpy(labels_n[split:])
    loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True)

    model = CNN1DDenoiser()
    opt = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
    loss_fn = nn.MSELoss()
    history = []

    for epoch in range(1, EPOCHS + 1):
        model.train()
        losses = []
        for batch_x, batch_y in loader:
            opt.zero_grad()
            pred = model(batch_x)
            loss = loss_fn(pred, batch_y)
            loss.backward()
            opt.step()
            losses.append(float(loss.detach()))
        model.eval()
        with torch.no_grad():
            val_pred = model(val_x)
            val_loss = float(loss_fn(val_pred, val_y))
        history.append((epoch, float(np.mean(losses)), val_loss))
        print("epoch %02d train_loss=%.6f val_loss=%.6f" % history[-1])

    model.eval()
    with torch.no_grad():
        pred_n = model(torch.from_numpy(wins_n)).numpy()
    pred = pred_n * y_std + y_mean
    full = np.full_like(x, np.nan, dtype=np.float32)
    full[centers] = pred.astype(np.float32)
    return full, centers, history


def roll_pitch_from_acc(data):
    ax = data[:, 0]
    ay = data[:, 1]
    az = data[:, 2]
    roll = np.degrees(np.arctan2(ay, az))
    pitch = np.degrees(np.arctan2(-ax, np.sqrt(ay * ay + az * az)))
    return np.column_stack([roll, pitch])


def metrics_for_method(name, values, centers):
    valid = values[centers]
    ref = np.nanmean(valid, axis=0)
    residual = valid - ref
    rows = []
    for i, ch in enumerate(CHANNELS):
        std = float(np.nanstd(valid[:, i]))
        rmse = float(np.sqrt(np.nanmean(residual[:, i] ** 2)))
        signal_rms = float(abs(ref[i]) + 1e-12)
        snr = 20.0 * math.log10(signal_rms / (rmse + 1e-12))
        rows.append({
            "method": name,
            "channel": ch,
            "mean": ref[i],
            "std": std,
            "rmse": rmse,
            "snr_db": snr,
        })

    rp = roll_pitch_from_acc(valid)
    rp_ref = np.nanmean(rp, axis=0)
    rp_res = rp - rp_ref
    for i, ch in enumerate(["roll_from_acc", "pitch_from_acc"]):
        std = float(np.nanstd(rp[:, i]))
        rmse = float(np.sqrt(np.nanmean(rp_res[:, i] ** 2)))
        signal_rms = float(abs(rp_ref[i]) + 1e-12)
        snr = 20.0 * math.log10(signal_rms / (rmse + 1e-12))
        rows.append({
            "method": name,
            "channel": ch,
            "mean": rp_ref[i],
            "std": std,
            "rmse": rmse,
            "snr_db": snr,
        })
    return rows


def save_tables(source_path, sample_rate, history, metrics):
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    hist_path = ANALYSIS_DIR / "ai_denoise_training_history.csv"
    with hist_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["epoch", "train_loss", "val_loss"])
        writer.writerows(history)

    metrics_path = ANALYSIS_DIR / "ai_denoise_metrics.csv"
    with metrics_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["method", "channel", "mean", "std", "rmse", "snr_db"])
        writer.writeheader()
        for row in metrics:
            writer.writerow({
                "method": row["method"],
                "channel": row["channel"],
                "mean": "%.9f" % row["mean"],
                "std": "%.9f" % row["std"],
                "rmse": "%.9f" % row["rmse"],
                "snr_db": "%.6f" % row["snr_db"],
            })

    summary_path = ANALYSIS_DIR / "ai_denoise_summary.csv"
    with summary_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["item", "value", "unit", "note"])
        writer.writerow(["source_file", source_path.name, "", "stationary IMU data"])
        writer.writerow(["sample_rate", "%.6f" % sample_rate, "Hz", "from CSV metadata"])
        writer.writerow(["window", WINDOW, "samples", "six-channel CNN input"])
        writer.writerow(["stride", STRIDE, "samples", "training/evaluation stride"])
        writer.writerow(["epochs", EPOCHS, "epochs", "1D-CNN training"])

    return hist_path, metrics_path, summary_path


def make_figures(t, raw, lowpass, kalman, cnn, centers, history):
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    plt.rcParams["font.sans-serif"] = ["DejaVu Sans", "Arial"]
    plt.rcParams["axes.unicode_minus"] = False

    hist = np.asarray(history)
    fig, ax = plt.subplots(figsize=(8, 4.8))
    ax.plot(hist[:, 0], hist[:, 1], marker="o", label="Train loss", color="#f97316")
    ax.plot(hist[:, 0], hist[:, 2], marker="o", label="Validation loss", color="#2563eb")
    ax.set_title("1D-CNN denoising training curve")
    ax.set_xlabel("Epoch")
    ax.set_ylabel("MSE loss")
    ax.grid(True, alpha=0.25)
    ax.legend()
    fig.tight_layout()
    train_path = FIG_DIR / "ai_denoise_training_curve.png"
    fig.savefig(train_path, dpi=180)
    plt.close(fig)

    start = centers[len(centers) // 3]
    end = min(start + 1200, len(raw))
    ts = t[start:end] - t[start]
    fig, axes = plt.subplots(3, 1, figsize=(10.5, 7), sharex=True)
    for ax, idx, name in zip(axes, [0, 1, 5], ["ax_g", "ay_g", "gz_dps"]):
        ax.plot(ts, raw[start:end, idx], label="Raw", color="#9ca3af", linewidth=0.7)
        ax.plot(ts, lowpass[start:end, idx], label="Low-pass", color="#f97316", linewidth=0.9)
        ax.plot(ts, kalman[start:end, idx], label="Kalman", color="#16a34a", linewidth=0.9)
        ax.plot(ts, cnn[start:end, idx], label="1D-CNN", color="#2563eb", linewidth=0.9)
        ax.set_ylabel(name)
        ax.grid(True, alpha=0.25)
    axes[0].set_title("Denoising comparison on stationary IMU signals")
    axes[-1].set_xlabel("Time (s)")
    axes[0].legend(loc="upper right")
    fig.tight_layout()
    compare_path = FIG_DIR / "ai_denoise_signal_compare.png"
    fig.savefig(compare_path, dpi=180)
    plt.close(fig)

    roll_raw = roll_pitch_from_acc(raw[centers])
    roll_low = roll_pitch_from_acc(lowpass[centers])
    roll_kal = roll_pitch_from_acc(kalman[centers])
    roll_cnn = roll_pitch_from_acc(cnn[centers])
    tt = t[centers] - t[centers][0]
    fig, axes = plt.subplots(2, 1, figsize=(10.5, 6.2), sharex=True)
    for ax, idx, name in zip(axes, [0, 1], ["roll_from_acc", "pitch_from_acc"]):
        ax.plot(tt, roll_raw[:, idx], label="Raw", color="#9ca3af", linewidth=0.6)
        ax.plot(tt, roll_low[:, idx], label="Low-pass", color="#f97316", linewidth=0.8)
        ax.plot(tt, roll_kal[:, idx], label="Kalman", color="#16a34a", linewidth=0.8)
        ax.plot(tt, roll_cnn[:, idx], label="1D-CNN", color="#2563eb", linewidth=0.8)
        ax.set_ylabel(name + " (deg)")
        ax.grid(True, alpha=0.25)
    axes[0].set_title("Attitude jitter estimated from denoised accelerometer")
    axes[-1].set_xlabel("Time (s)")
    axes[0].legend(loc="upper right")
    fig.tight_layout()
    jitter_path = FIG_DIR / "ai_denoise_attitude_jitter.png"
    fig.savefig(jitter_path, dpi=180)
    plt.close(fig)

    return train_path, compare_path, jitter_path


def main():
    start_time = time.perf_counter()
    source_path, meta, rows = read_latest_csv()
    sample_rate = float(meta.get("sample_hz", 50))
    t = rows[:, 0] / 1000.0
    raw = rows[:, 1:7]

    lowpass = lowpass_iir(raw, LOWPASS_ALPHA)
    kalman = kalman_filter(raw)
    cnn, centers, history = train_cnn(raw, raw)

    metrics = []
    metrics.extend(metrics_for_method("raw", raw, centers))
    metrics.extend(metrics_for_method("lowpass", lowpass, centers))
    metrics.extend(metrics_for_method("kalman", kalman, centers))
    metrics.extend(metrics_for_method("cnn_1d", cnn, centers))

    hist_path, metrics_path, summary_path = save_tables(source_path, sample_rate, history, metrics)
    figs = make_figures(t, raw, lowpass, kalman, cnn, centers, history)

    print("Source:", source_path)
    print("Samples:", len(raw))
    print("Windows:", len(centers))
    print("Runtime: %.2f s" % (time.perf_counter() - start_time))
    print("Wrote:", hist_path)
    print("Wrote:", metrics_path)
    print("Wrote:", summary_path)
    for fig in figs:
        print("Figure:", fig)

    print("")
    print("Key metric preview: roll/pitch jitter std")
    for method in ("raw", "lowpass", "kalman", "cnn_1d"):
        rows_m = [r for r in metrics if r["method"] == method and r["channel"] in ("roll_from_acc", "pitch_from_acc")]
        print(method, ", ".join("%s=%.4f deg" % (r["channel"], r["std"]) for r in rows_m))


if __name__ == "__main__":
    main()
