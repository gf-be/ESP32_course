"""
Six-position accelerometer calibration with a 12-parameter affine model.

Model:
    raw = M * true + b

M is a 3x3 scale/misalignment matrix and b is a 3-axis bias vector. The
firmware-friendly inverse form is also exported:
    calibrated = C * raw + d
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

TARGETS = {
    "pos_x_up": (1.0, 0.0, 0.0),
    "neg_x_up": (-1.0, 0.0, 0.0),
    "pos_y_up": (0.0, 1.0, 0.0),
    "neg_y_up": (0.0, -1.0, 0.0),
    "pos_z_up": (0.0, 0.0, 1.0),
    "neg_z_up": (0.0, 0.0, -1.0),
}

PAIRS = {
    "x": ("pos_x_up", "neg_x_up", 0),
    "y": ("pos_y_up", "neg_y_up", 1),
    "z": ("pos_z_up", "neg_z_up", 2),
}


def read_csv(path):
    rows = []
    with path.open("r", encoding="utf-8") as f:
        reader = csv.reader(line for line in f if not line.startswith("#"))
        header = next(reader)
        idx = {name: header.index(name) for name in ("ax_g", "ay_g", "az_g")}
        for row in reader:
            if row:
                rows.append((float(row[idx["ax_g"]]), float(row[idx["ay_g"]]), float(row[idx["az_g"]])))
    return rows


def latest_file_for_position(data_dir, position):
    files = sorted(data_dir.glob(position + "_*.csv"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise FileNotFoundError("No CSV file found for %s in %s" % (position, data_dir))
    return files[-1]


def project_root():
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "firmware").is_dir() and (parent / "data").is_dir():
            return parent
    return here.parent


def mean_vector(rows):
    return tuple(statistics.fmean(col) for col in zip(*rows))


def vector_norm(v):
    return math.sqrt(sum(x * x for x in v))


def norm_error_mg(v):
    return abs(vector_norm(v) - 1.0) * 1000.0


def vec_add(a, b):
    return tuple(x + y for x, y in zip(a, b))


def vec_sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def vec_scale(v, k):
    return tuple(k * x for x in v)


def mat_vec(m, v):
    return tuple(sum(m[r][c] * v[c] for c in range(3)) for r in range(3))


def inv3(m):
    a, b, c = m[0]
    d, e, f = m[1]
    g, h, i = m[2]
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if abs(det) < 1e-12:
        raise ValueError("12-parameter matrix is singular")
    k = 1.0 / det
    return (
        ((e * i - f * h) * k, (c * h - b * i) * k, (b * f - c * e) * k),
        ((f * g - d * i) * k, (a * i - c * g) * k, (c * d - a * f) * k),
        ((d * h - e * g) * k, (b * g - a * h) * k, (a * e - b * d) * k),
    )


def build_diag6(means):
    bias = {}
    scale = {}
    for axis, (pos_p, pos_n, idx) in PAIRS.items():
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

    return bias, scale, calibrate


def build_affine12(means):
    pair_centers = []
    columns = []
    for axis in AXES:
        pos_p, pos_n, _ = PAIRS[axis]
        plus = means[pos_p]
        minus = means[pos_n]
        pair_centers.append(vec_scale(vec_add(plus, minus), 0.5))
        columns.append(vec_scale(vec_sub(plus, minus), 0.5))

    bias = tuple(statistics.fmean(center[i] for center in pair_centers) for i in range(3))
    matrix = tuple(tuple(columns[c][r] for c in range(3)) for r in range(3))
    inverse = inv3(matrix)
    offset = vec_scale(mat_vec(inverse, bias), -1.0)

    def calibrate(v):
        return mat_vec(inverse, vec_sub(v, bias))

    return bias, matrix, inverse, offset, pair_centers, calibrate


def sample_error_summary(rows_by_pos, calibrate):
    errors = []
    for pos in POSITIONS:
        for row in rows_by_pos[pos]:
            errors.append(norm_error_mg(calibrate(row)))
    return (
        statistics.fmean(errors),
        math.sqrt(statistics.fmean(e * e for e in errors)),
        max(errors),
    )


def write_means(out_dir, files, counts, means, diag_cal, affine_cal):
    path = out_dir / "accel_6pos_means.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "position", "source_file", "samples",
            "mean_ax_g", "mean_ay_g", "mean_az_g", "raw_norm_g", "raw_error_mg",
            "diag6_ax_g", "diag6_ay_g", "diag6_az_g", "diag6_norm_g", "diag6_error_mg",
            "affine12_ax_g", "affine12_ay_g", "affine12_az_g", "affine12_norm_g", "affine12_error_mg",
            "target_ax_g", "target_ay_g", "target_az_g",
        ])
        for pos in POSITIONS:
            raw = means[pos]
            diag = diag_cal(raw)
            aff = affine_cal(raw)
            w.writerow([
                pos, files[pos].name, counts[pos],
                "%.8f" % raw[0], "%.8f" % raw[1], "%.8f" % raw[2],
                "%.8f" % vector_norm(raw), "%.3f" % norm_error_mg(raw),
                "%.8f" % diag[0], "%.8f" % diag[1], "%.8f" % diag[2],
                "%.8f" % vector_norm(diag), "%.3f" % norm_error_mg(diag),
                "%.8f" % aff[0], "%.8f" % aff[1], "%.8f" % aff[2],
                "%.8f" % vector_norm(aff), "%.3f" % norm_error_mg(aff),
                "%.1f" % TARGETS[pos][0], "%.1f" % TARGETS[pos][1], "%.1f" % TARGETS[pos][2],
            ])
    return path


def write_diag6(out_dir, bias, scale):
    path = out_dir / "accel_6pos_calibration_params.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["axis", "bias_g", "scale_g_per_g", "calibration_formula"])
        for axis in AXES:
            w.writerow([
                axis,
                "%.8f" % bias[axis],
                "%.8f" % scale[axis],
                "(raw_%s_g - %.8f) / %.8f" % (axis, bias[axis], scale[axis]),
            ])
    return path


def write_affine12(out_dir, bias, matrix, inverse, offset):
    matrix_path = out_dir / "accel_6pos_12param_matrix.csv"
    with matrix_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["raw_axis", "true_x_coeff", "true_y_coeff", "true_z_coeff", "bias_g", "model"])
        for r, axis in enumerate(AXES):
            w.writerow([
                "raw_" + axis,
                "%.10f" % matrix[r][0],
                "%.10f" % matrix[r][1],
                "%.10f" % matrix[r][2],
                "%.10f" % bias[r],
                "raw = M * true + b",
            ])

    inverse_path = out_dir / "accel_6pos_12param_inverse.csv"
    with inverse_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["cal_axis", "raw_x_coeff", "raw_y_coeff", "raw_z_coeff", "offset_g", "firmware_formula"])
        for r, axis in enumerate(AXES):
            formula = (
                "cal_%s = %.10f*raw_x + %.10f*raw_y + %.10f*raw_z + %.10f"
                % (axis, inverse[r][0], inverse[r][1], inverse[r][2], offset[r])
            )
            w.writerow([
                "cal_" + axis,
                "%.10f" % inverse[r][0],
                "%.10f" % inverse[r][1],
                "%.10f" % inverse[r][2],
                "%.10f" % offset[r],
                formula,
            ])
    return matrix_path, inverse_path


def write_pair_centers(out_dir, bias, pair_centers):
    path = out_dir / "accel_6pos_pair_centers.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["axis_pair", "center_ax_g", "center_ay_g", "center_az_g", "delta_from_common_bias_mg"])
        for axis, center in zip(AXES, pair_centers):
            delta = vec_sub(center, bias)
            w.writerow([
                axis,
                "%.8f" % center[0],
                "%.8f" % center[1],
                "%.8f" % center[2],
                "%.3f" % (vector_norm(delta) * 1000.0),
            ])
    return path


def write_compare(out_dir, rows_by_pos, means, diag_cal, affine_cal):
    def identity(v):
        return v

    raw_mean = [norm_error_mg(means[pos]) for pos in POSITIONS]
    diag_mean = [norm_error_mg(diag_cal(means[pos])) for pos in POSITIONS]
    aff_mean = [norm_error_mg(affine_cal(means[pos])) for pos in POSITIONS]
    raw_sample = sample_error_summary(rows_by_pos, identity)
    diag_sample = sample_error_summary(rows_by_pos, diag_cal)
    aff_sample = sample_error_summary(rows_by_pos, affine_cal)
    raw_avg = statistics.fmean(raw_mean)

    rows = [
        ("raw", raw_mean, raw_sample, "uncalibrated"),
        ("diag6_bias_scale", diag_mean, diag_sample, "diagonal bias and scale only"),
        ("affine12_bias_scale_misalignment", aff_mean, aff_sample, "bias, scale and axis misalignment"),
    ]

    path = out_dir / "accel_6pos_model_compare.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "model", "mean_vector_avg_error_mg", "mean_vector_max_error_mg",
            "mean_vector_rms_error_mg", "sample_mae_error_mg", "sample_rms_error_mg",
            "sample_max_error_mg", "improvement_vs_raw_mean_vector", "note",
        ])
        for name, mean_errors, sample_errors, note in rows:
            avg = statistics.fmean(mean_errors)
            rms = math.sqrt(statistics.fmean(e * e for e in mean_errors))
            w.writerow([
                name,
                "%.3f" % avg,
                "%.3f" % max(mean_errors),
                "%.3f" % rms,
                "%.3f" % sample_errors[0],
                "%.3f" % sample_errors[1],
                "%.3f" % sample_errors[2],
                "%.3f" % (raw_avg / avg if avg > 0 else 0.0),
                note,
            ])
    return path


def main():
    root = project_root()
    data_dir = root / "data" / "calibration"
    out_dir = root / "data"

    files = {pos: latest_file_for_position(data_dir, pos) for pos in POSITIONS}
    rows_by_pos = {}
    means = {}
    counts = {}
    for pos, path in files.items():
        rows = read_csv(path)
        rows_by_pos[pos] = rows
        means[pos] = mean_vector(rows)
        counts[pos] = len(rows)

    diag_bias, diag_scale, diag_cal = build_diag6(means)
    affine_bias, matrix, inverse, offset, pair_centers, affine_cal = build_affine12(means)

    written = [
        write_means(out_dir, files, counts, means, diag_cal, affine_cal),
        write_diag6(out_dir, diag_bias, diag_scale),
        write_pair_centers(out_dir, affine_bias, pair_centers),
        write_compare(out_dir, rows_by_pos, means, diag_cal, affine_cal),
    ]
    written.extend(write_affine12(out_dir, affine_bias, matrix, inverse, offset))

    print("Data directory:", data_dir)
    print("Output directory:", out_dir)
    print("")
    print("Affine 12-parameter model: raw = M * true + b")
    print("b = (%.8f, %.8f, %.8f) g" % affine_bias)
    for row in matrix:
        print("M row: %.8f %.8f %.8f" % row)
    print("")
    print("Wrote:")
    for path in written:
        print(" ", path)


if __name__ == "__main__":
    main()
