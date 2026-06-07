# Final Group Accelerometer Calibration Result

Date: 2026-06-05

Source file: `accel_6pos_means_final_group.csv`

## Six-Position Means

| Position | Label | True vector | ax_mean | ay_mean | az_mean | norm_mean | Rows |
|---|---|---:|---:|---:|---:|---:|---:|
| P1 | +X | (1, 0, 0) | 1.00349123 | 0.01160145 | 0.06573910 | 1.00570914 | 1200 |
| P2 | -X | (-1, 0, 0) | -0.99591521 | 0.00084545 | -0.03908746 | 0.99668232 | 1200 |
| P3 | -Y | (0, -1, 0) | 0.00793681 | -0.99099345 | -0.05464098 | 0.99253043 | 1200 |
| P4 | +Y | (0, 1, 0) | -0.00046079 | 1.00354035 | 0.08121262 | 1.00682120 | 1200 |
| P5 | -Z | (0, 0, -1) | 0.05881365 | 0.07948857 | -1.00210362 | 1.00697028 | 1200 |
| P6 | +Z | (0, 0, 1) | -0.05128763 | -0.06696167 | 1.02866526 | 1.03211749 | 1200 |

## Model

Measured acceleration model:

```text
measured = A * true + c
```

A matrix:

```text
[[ 0.99970322 -0.0041988  -0.05505064]
 [ 0.005378    0.9972669  -0.07322512]
 [ 0.05241328  0.0679268   1.01538444]]
```

c bias:

```text
[0.00376301 0.00625345 0.01329749]
```

Firmware correction:

```c
static const float ACCEL_A_INV[3][3] = {
    {0.99745688f, 0.00051362f, 0.05411571f},
    {-0.00911479f, 0.99783450f, 0.07146532f},
    {-0.05087812f, -0.06677926f, 0.97727439f},
};
static const float ACCEL_C_BIAS[3] = {0.00376301f, 0.00625345f, 0.01329749f};
```

## Error Summary

| Position | Before | After |
|---|---:|---:|
| P1 | 5.709 mg | 0.026 mg |
| P2 | 3.318 mg | 0.026 mg |
| P3 | 7.470 mg | 0.019 mg |
| P4 | 6.821 mg | 0.019 mg |
| P5 | 6.970 mg | 0.017 mg |
| P6 | 32.117 mg | 0.017 mg |
| Mean | 10.401 mg | 0.021 mg |

Mean before: 10.401 mg

Mean after: 0.021 mg

Improvement ratio: 497.17x

Figure: `report_assets/figures/fig_accel_final_group_calibration_errors.png`

Vector error check:

- Mean vector error before: 71.896 mg
- Mean vector error after: 0.034 mg
