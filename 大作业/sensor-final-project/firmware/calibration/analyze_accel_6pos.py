"""
Analyze six-position accelerometer CSV files captured by pc_accel_6pos_capture.py.

Run this file on the computer. It reads the latest six CSV files in
data/accel_6pos, estimates simple bias/scale calibration parameters, and writes
summary CSV files for the report.
"""

from pathlib import Path
import csv
import math
import statistics


POSITIONS = [
    "pos_x_up",
    "neg_x_up",
    "pos_y_up",
    "neg_y_up",
    "pos_z_up",
    "neg_z_up",
]

AXES = ["x", "y", "z"]


def read_csv(path):
    rows = []
    with path.open("r", encoding="utf-8") as f:
        reader = csv.reader(line for line in f if not line.startswith("#"))
        header = next(reader)
        idx = {name: header.index(name) for name in ("ax_g", "ay_g", "az_g")}
        for row in reader:
            if not row:
                continue
            rows.append((float(row[idx["ax_g"]]), float(row[idx["ay_g"]]), float(row[idx["az_g"]])))
    return rows


def latest_file_for_position(data_dir, position):
    files = sorted(data_dir.glob(position + "_*.csv"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise FileNotFoundError("No CSV file found for %s in %s" % (position, data_dir))
    return files[-1]


def mean_vector(rows):
    return tuple(statistics.fmean(col) for col in zip(*rows))


def vector_norm(v):
    return math.sqrt(sum(x * x for x in v))


def main():
    root = Path(__file__).resolve().parent
    data_dir = root / "data" / "accel_6pos"
    out_dir = root / "data" / "analysis"
    out_dir.mkdir(parents=True, exist_ok=True)

    files = {pos: latest_file_for_position(data_dir, pos) for pos in POSITIONS}
    means = {}
    counts = {}
    for pos, path in files.items():
        rows = read_csv(path)
        means[pos] = mean_vector(rows)
        counts[pos] = len(rows)

    # Simple diagonal six-position calibration:
    # raw = scale * true + bias, where true is +/-1 g on the upward axis.
    bias = {}
    scale = {}
    pairs = {
        "x": ("pos_x_up", "neg_x_up", 0),
        "y": ("pos_y_up", "neg_y_up", 1),
        "z": ("pos_z_up", "neg_z_up", 2),
    }
    for axis, (pos_p, pos_n, idx) in pairs.items():
        plus = means[pos_p][idx]
        minus = means[pos_n][idx]
        bias[axis] = (plus + minus) / 2.0
        scale[axis] = (plus - minus) / 2.0

    def calibrate(v):
        return (
            (v[0] - bias["x"]) / scale["x"],
            (v[1] - bias["y"]) / scale["y"],
            (v[2] - bias["z"]) / scale["z"],
        )

    means_path = out_dir / "accel_6pos_means.csv"
    with means_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "position",
            "source_file",
            "samples",
            "mean_ax_g",
            "mean_ay_g",
            "mean_az_g",
            "raw_norm_g",
            "raw_error_mg",
            "cal_ax_g",
            "cal_ay_g",
            "cal_az_g",
            "cal_norm_g",
            "cal_error_mg",
        ])
        for pos in POSITIONS:
            raw = means[pos]
            cal = calibrate(raw)
            raw_norm = vector_norm(raw)
            cal_norm = vector_norm(cal)
            writer.writerow([
                pos,
                files[pos].name,
                counts[pos],
                "%.8f" % raw[0],
                "%.8f" % raw[1],
                "%.8f" % raw[2],
                "%.8f" % raw_norm,
                "%.3f" % (abs(raw_norm - 1.0) * 1000.0),
                "%.8f" % cal[0],
                "%.8f" % cal[1],
                "%.8f" % cal[2],
                "%.8f" % cal_norm,
                "%.3f" % (abs(cal_norm - 1.0) * 1000.0),
            ])

    params_path = out_dir / "accel_6pos_calibration_params.csv"
    with params_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["axis", "bias_g", "scale_g_per_g", "calibration_formula"])
        for axis in AXES:
            writer.writerow([
                axis,
                "%.8f" % bias[axis],
                "%.8f" % scale[axis],
                "(raw_%s_g - %.8f) / %.8f" % (axis, bias[axis], scale[axis]),
            ])

    print("Files used:")
    for pos in POSITIONS:
        print("  %-10s %s" % (pos, files[pos]))
    print("")
    print("Calibration parameters:")
    for axis in AXES:
        print("  %s: bias=%.8f g, scale=%.8f" % (axis, bias[axis], scale[axis]))
    print("")
    print("Wrote:")
    print(" ", means_path)
    print(" ", params_path)


if __name__ == "__main__":
    main()
