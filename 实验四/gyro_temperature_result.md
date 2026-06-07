# New MPU6500 Gyroscope Temperature Result

Date: 2026-06-05

This file records gyroscope temperature and drift observations for the new true MPU6500 board only.

## Important Correction

The first temperature recordings were produced before the firmware temperature formula was corrected. The firmware used the MPU6050 formula:

```text
temp_old = raw / 340 + 36.53
```

For the true MPU6500 board, the corrected formula is:

```text
temp_mpu6500 = raw / 333.87 + 21.0
```

The source CSV files recorded before the firmware fix still contain the old `temp_c` values, but the temperature values in this report are converted to MPU6500-equivalent temperatures. The gyroscope and accelerometer values are not affected by this correction.

Firmware was corrected and flashed after this issue was found. The check file `temp_formula_fixed_check.csv` reports a reasonable room-temperature reading of about 25.55 degC.

## Corrected Room-Temperature Static Baseline

Source file: `gyro_room_baseline_180s.csv`

Duration: 180 s

Rows: 7184

| Signal | Mean | Std | Min | Max |
|---|---:|---:|---:|---:|
| gx_dps | 0.655513 | 0.044807 | 0.496000 | 0.832000 |
| gy_dps | 1.054959 | 0.059371 | 0.840000 | 1.282000 |
| gz_dps | -0.097135 | 0.054698 | -0.450000 | 0.145000 |
| temp_c_corrected | 27.014914 | 0.097537 | 26.794471 | 27.191631 |

## Corrected Room Baseline 60-Second Segments

| Segment | gx_mean | gy_mean | gz_mean | temp_mean_corrected |
|---|---:|---:|---:|---:|
| First 60 s | 0.654141 | 1.056875 | -0.100818 | 27.111230 |
| Middle 60 s | 0.658020 | 1.053730 | -0.096183 | 27.042538 |
| Last 60 s | 0.654377 | 1.054271 | -0.094407 | 26.891013 |

## Corrected Room Baseline First and Last Approximate 10-Second Means

| Window | gx_mean | gy_mean | gz_mean | temp_mean_corrected |
|---|---:|---:|---:|---:|
| First 10 s | 0.654825 | 1.055192 | -0.092160 | 27.124547 |
| Last 10 s | 0.657930 | 1.052280 | -0.096348 | 26.863032 |
| Last - First | 0.003105 | -0.002913 | -0.004187 | -0.261515 |

Baseline note: during the 180 s room-temperature static recording, the gyroscope offset was stable. The last-minus-first 10 s change was only about 0.003 to 0.004 deg/s on each axis while the corrected temperature decreased by about 0.262 degC.

## Corrected Post-Fridge Static Recording

Source file: `gyro_warmup_after_fridge_600s.csv`

Duration: 600 s

Rows: 24001

| Signal | Mean | Std | Min | Max |
|---|---:|---:|---:|---:|
| gx_dps | 0.633788 | 0.118148 | 0.099000 | 1.107000 |
| gy_dps | 1.112053 | 0.154284 | 0.084000 | 1.794000 |
| gz_dps | 0.021161 | 0.153233 | -2.359000 | 2.458000 |
| temp_c_corrected | 25.613373 | 0.311050 | 24.981789 | 26.794471 |

## Corrected Post-Fridge 60-Second Segment Means

| Minute | temp_mean_corrected | gx_mean | gy_mean | gz_mean |
|---:|---:|---:|---:|---:|
| 1 | 26.2588 | 0.63885 | 1.11708 | 0.03354 |
| 2 | 25.9878 | 0.62990 | 1.10510 | 0.03016 |
| 3 | 25.8133 | 0.63827 | 1.10626 | 0.02034 |
| 4 | 25.5532 | 0.64572 | 1.11586 | 0.01818 |
| 5 | 25.4630 | 0.63349 | 1.11182 | 0.02042 |
| 6 | 25.4183 | 0.63362 | 1.10983 | 0.02076 |
| 7 | 25.4094 | 0.63447 | 1.11435 | 0.01996 |
| 8 | 25.3991 | 0.63037 | 1.11164 | 0.01139 |
| 9 | 25.3967 | 0.62586 | 1.11620 | 0.01461 |
| 10 | 25.4342 | 0.62734 | 1.11239 | 0.02226 |

## Corrected Post-Fridge First and Last Approximate 10-Second Means

| Window | gx_mean | gy_mean | gz_mean | temp_mean_corrected |
|---|---:|---:|---:|---:|
| First 10 s | 0.636992 | 1.124702 | 0.035715 | 26.407901 |
| Last 10 s | 0.623803 | 1.109080 | 0.028735 | 25.486311 |
| Last - First | -0.013190 | -0.015622 | -0.006980 | -0.921591 |

## Corrected Temperature Linear Fit

Model:

```text
gyro_bias = slope * temp_c_corrected + intercept
```

| Axis | Slope (deg/s/degC) | Intercept | R2 |
|---|---:|---:|---:|
| gx | 0.00546979 | 0.49368871 | 0.000207 |
| gy | 0.00035389 | 1.10298880 | 0.000001 |
| gz | 0.01488459 | -0.36008344 | 0.000913 |

Post-fridge note: after correction, the post-fridge file only spans about 24.98 to 26.79 degC. This is not a successful wide-range refrigerator temperature experiment. It can only support the limited statement that near room temperature, the gyroscope bias did not show a strong linear relationship with temperature in this recording.

## Firmware Fix Check

Source file: `temp_formula_fixed_check.csv`

Rows: 304

| Signal | Mean | Std | Min | Max |
|---|---:|---:|---:|---:|
| gx_dps | 0.625105 | 0.043708 | 0.504000 | 0.733000 |
| gy_dps | 1.077132 | 0.061247 | 0.908000 | 1.267000 |
| gz_dps | -0.088776 | 0.058837 | -0.229000 | 0.099000 |
| temp_c | 25.551612 | 0.018683 | 25.510000 | 25.600000 |

Conclusion: the firmware temperature output is now reasonable for the MPU6500. The previous post-fridge experiment is not strong enough for a strict temperature compensation model and should be reported as a limited near-room-temperature drift observation, or repeated with a better cold-start procedure if a clear temperature sweep is required.

## Ice-Pack Cooling and Warmup Recording

Source file: `gyro_icepack_cooling_warmup_600s.csv`

Duration: 600 s

Rows: 23985

Procedure: the ice pack was kept close to the MPU6500 for about the first 5 minutes, then removed gently while the sensor stayed still for natural warmup.

### Full Data Summary

| Signal | Mean | Std | Min | Max |
|---|---:|---:|---:|---:|
| gx_dps | 0.683398 | 0.102642 | -8.015000 | 1.115000 |
| gy_dps | 1.127656 | 0.123425 | -3.252000 | 12.260000 |
| gz_dps | -0.242443 | 0.115559 | -4.534000 | 8.527000 |
| temp_c | 16.371241 | 2.904171 | 13.090000 | 22.020000 |
| accel_norm_g | 1.015330 | 0.003658 | 0.904114 | 1.139342 |

The large full-data gyro min/max values are caused by brief mechanical disturbance while handling the ice pack. For temperature-drift analysis, the static-point filtered data below is preferred.

### Static-Point Filtered Summary

Static-point filter: `0.98 <= |a| <= 1.04` and `abs(gx), abs(gy), abs(gz) < 2.5 deg/s`.

Filtered rows: 23964 of 23985. Removed rows: 21.

| Signal | Mean | Std | Min | Max |
|---|---:|---:|---:|---:|
| gx_dps | 0.684803 | 0.054763 | 0.229000 | 0.947000 |
| gy_dps | 1.126860 | 0.064052 | 0.473000 | 2.466000 |
| gz_dps | -0.243136 | 0.075043 | -1.725000 | 1.527000 |
| temp_c | 16.373706 | 2.904159 | 13.090000 | 22.020000 |
| accel_norm_g | 1.015309 | 0.003130 | 0.991946 | 1.035823 |

### Minute Means After Static-Point Filtering

| Minute | temp_mean | gx_mean | gy_mean | gz_mean |
|---:|---:|---:|---:|---:|
| 1 | 17.0497 | 0.67290 | 1.12575 | -0.24358 |
| 2 | 15.3848 | 0.67884 | 1.12552 | -0.26611 |
| 3 | 14.2547 | 0.68855 | 1.12645 | -0.26771 |
| 4 | 13.6037 | 0.68860 | 1.12735 | -0.27464 |
| 5 | 13.2994 | 0.73314 | 1.12936 | -0.29583 |
| 6 | 13.2601 | 0.72299 | 1.13629 | -0.28481 |
| 7 | 16.0980 | 0.70375 | 1.13621 | -0.24422 |
| 8 | 18.7814 | 0.67569 | 1.12856 | -0.20359 |
| 9 | 20.4422 | 0.65318 | 1.12096 | -0.17534 |
| 10 | 21.5707 | 0.63033 | 1.11215 | -0.17545 |

### Key Windows

| Window | gx_mean | gy_mean | gz_mean | temp_mean | accel_norm_mean |
|---|---:|---:|---:|---:|---:|
| First 10 s | 0.667340 | 1.122613 | -0.232405 | 17.998150 | 1.013280 |
| Lowest-temp window | 0.730865 | 1.127115 | -0.300368 | 13.136475 | 1.018444 |
| Last 10 s | 0.626090 | 1.110800 | -0.166640 | 21.926825 | 1.011194 |

### Static-Point Filtered Linear Fit

Model:

```text
gyro_bias = slope * temp_c + intercept
```

| Axis | Slope (deg/s/degC) | Intercept | R2 |
|---|---:|---:|---:|
| gx | -0.00883187 | 0.82941352 | 0.219371 |
| gy | -0.00165374 | 1.15393821 | 0.005622 |
| gz | 0.01430307 | -0.47733046 | 0.306394 |

Ice-pack conclusion: this recording produced a valid wider temperature span from about 13.09 to 22.02 degC. In this range, gx and gz show visible temperature-related bias changes, while gy has weak temperature correlation. The fit can be reported as an experimental linear compensation estimate, but the R2 values show that it is still a simple approximation rather than a high-precision compensation model.

### Manual-Style Binned Quadratic Fit

The lab manual recommends denoising by grouping samples into 0.5 degC temperature bins and using the median value in each bin before polynomial fitting. Using that method, the ice-pack data gives 19 valid temperature bins from 13.0 to 22.0 degC.

Model:

```text
gyro_bias = c0 + c1*T + c2*T*T
```

| Axis | c0 | c1 | c2 | Binned residual std | Binned improvement |
|---|---:|---:|---:|---:|---:|
| gx | 0.7319705145 | 0.0022361197 | -0.0003042901 | 0.009083 deg/s | 2.736x |
| gy | 1.0369519387 | 0.0122930857 | -0.0004033613 | 0.003572 deg/s | 1.878x |
| gz | -0.4898115878 | 0.0153560372 | -0.0000176913 | 0.006992 deg/s | 5.858x |

Manual-style assessment: the binned quadratic fit residuals are all below 0.05 deg/s. The remaining limitation is temperature range: the manual target is below 10 degC to room temperature, while this ice-pack run reached 13.09 degC to 22.02 degC.
