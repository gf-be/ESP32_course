from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
FIG = DATA / "figures"


def get_font() -> FontProperties:
    for path in [
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("C:/Windows/Fonts/simsun.ttc"),
    ]:
        if path.exists():
            return FontProperties(fname=str(path))
    return FontProperties()


def read_means():
    path = DATA / "accel_6pos_means.csv"
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def save_norm_compare(rows, font: FontProperties):
    labels = ["+X向上", "-X向上", "+Y向上", "-Y向上", "+Z向上", "-Z向上"]
    raw = [float(r["raw_norm_g"]) for r in rows]
    affine = [float(r["affine12_norm_g"]) for r in rows]

    fig, ax = plt.subplots(figsize=(9.5, 5.2), dpi=180)
    x = range(len(labels))
    ax.plot(x, raw, "-o", color="#f97316", linewidth=2.0, markersize=6, label="标定前模长")
    ax.plot(x, affine, "-o", color="#2563eb", linewidth=2.0, markersize=6, label="12参数标定后模长")
    ax.axhline(1.0, color="#111827", linestyle="--", linewidth=1.2, label="理想值 1 g")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, fontproperties=font, fontsize=10)
    ax.set_ylabel("加速度模长 (g)", fontproperties=font, fontsize=11)
    ax.set_title("六位置标定前后加速度模长与 1 g 对比", fontproperties=font, fontsize=14)
    ax.grid(True, alpha=0.28)
    ax.legend(prop=font, frameon=True)
    fig.tight_layout()
    out = FIG / "accel_6pos_norm_compare_cn.png"
    fig.savefig(out)
    plt.close(fig)
    return out


def save_error_compare(rows, font: FontProperties):
    labels = ["+X向上", "-X向上", "+Y向上", "-Y向上", "+Z向上", "-Z向上"]
    raw = [float(r["raw_error_mg"]) for r in rows]
    diag6 = [float(r["diag6_error_mg"]) for r in rows]
    affine = [float(r["affine12_error_mg"]) for r in rows]

    fig, ax = plt.subplots(figsize=(9.5, 5.2), dpi=180)
    x = list(range(len(labels)))
    width = 0.25
    ax.bar([i - width for i in x], raw, width=width, color="#f97316", label="标定前")
    ax.bar(x, diag6, width=width, color="#22c55e", label="6参数模型")
    ax.bar([i + width for i in x], affine, width=width, color="#2563eb", label="12参数仿射模型")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontproperties=font, fontsize=10)
    ax.set_ylabel("模长误差 (mg)", fontproperties=font, fontsize=11)
    ax.set_title("六位置标定前后加速度模长误差对比", fontproperties=font, fontsize=14)
    ax.grid(axis="y", alpha=0.28)
    ax.legend(prop=font, frameon=True)
    fig.tight_layout()
    out = FIG / "accel_6pos_error_compare_cn.png"
    fig.savefig(out)
    plt.close(fig)
    return out


def main():
    rows = read_means()
    font = get_font()
    FIG.mkdir(parents=True, exist_ok=True)
    for out in [save_error_compare(rows, font), save_norm_compare(rows, font)]:
        print(out)


if __name__ == "__main__":
    main()
