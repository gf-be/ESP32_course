# New MPU6500 Dynamic Observation Result

Date: 2026-06-05

This file records dynamic observations for the new true MPU6500 board only.

## Static Baseline

Source file: `vibration_baseline_static.csv`

Rows: 304

| Signal | Mean | Std | Min | Max |
|---|---:|---:|---:|---:|
| ax_g | 0.998526 | 0.002341 | 0.992400 | 1.004900 |
| ay_g | 0.005752 | 0.002080 | 0.000000 | 0.012500 |
| az_g | 0.128005 | 0.003477 | 0.119100 | 0.139600 |
| gx_dps | 0.635046 | 0.045472 | 0.511000 | 0.756000 |
| gy_dps | 1.061391 | 0.060775 | 0.817000 | 1.260000 |
| gz_dps | -0.107243 | 0.052398 | -0.252000 | 0.053000 |
| temp_c | 43.588487 | 0.023697 | 43.530000 | 43.640000 |
| accel_norm_g | 1.006722 | 0.002393 | 0.999699 | 1.013278 |

Static baseline note: the accelerometer norm is close to 1 g and has low noise. This baseline can be used to compare vibration and tapping data.

## Table Tap

Source file: `vibration_table_tap_rerun.csv`

Rows: 304

The first file `vibration_table_tap.csv` was not used because the start cue was missed and its statistics were close to the static baseline.

| Signal | Mean | Std | Min | Max |
|---|---:|---:|---:|---:|
| ax_g | 0.996046 | 0.050448 | 0.612500 | 1.293000 |
| ay_g | 0.005591 | 0.048340 | -0.236600 | 0.653800 |
| az_g | 0.133643 | 0.028228 | -0.160400 | 0.262700 |
| gx_dps | 0.636934 | 0.141105 | -0.107000 | 1.939000 |
| gy_dps | 1.119385 | 2.043696 | -16.931000 | 16.069000 |
| gz_dps | -0.118753 | 1.073261 | -9.618000 | 5.748000 |
| temp_c | 43.785888 | 0.038112 | 43.700000 | 43.880000 |
| accel_norm_g | 1.006607 | 0.049189 | 0.654413 | 1.351591 |

Tap observation note: compared with the static baseline, the accelerometer norm standard deviation increased from 0.002393 g to 0.049189 g, about 20.56x. The gyroscope also showed clear transient peaks, especially on the Y and Z axes.

## Phone Vibration

Source file: `vibration_phone.csv`

Rows: 264

| Signal | Mean | Std | Min | Max |
|---|---:|---:|---:|---:|
| ax_g | 0.995181 | 0.010858 | 0.969500 | 1.018800 |
| ay_g | 0.003802 | 0.081278 | -0.167500 | 0.165000 |
| az_g | 0.155561 | 0.031473 | 0.056600 | 0.262000 |
| gx_dps | 0.651867 | 0.051220 | 0.534000 | 0.802000 |
| gy_dps | 1.060981 | 0.087487 | 0.824000 | 1.305000 |
| gz_dps | -0.132280 | 0.143911 | -0.450000 | 0.214000 |
| temp_c | 43.144848 | 0.018484 | 43.100000 | 43.200000 |
| accel_norm_g | 1.011051 | 0.009407 | 0.993558 | 1.048705 |

Phone vibration note: compared with the static baseline, the accelerometer norm standard deviation increased from 0.002393 g to 0.009407 g, about 3.93x. This vibration was weaker than the table tap result but still clearly above the static baseline.

## Rotation Observation

Source file: `rotation_observation_rerun.csv`

Rows: 304

The first file `rotation_observation.csv` mainly captured a sustained rotation around one axis. The rerun file is used as the final rotation observation because the accelerometer components changed clearly across axes.

| Signal | Mean | Std | Min | Max |
|---|---:|---:|---:|---:|
| ax_g | -0.623516 | 0.371418 | -1.080600 | 0.361300 |
| ay_g | -0.262530 | 0.596901 | -1.063700 | 0.984900 |
| az_g | -0.094573 | 0.172870 | -0.394300 | 0.304200 |
| gx_dps | -4.532635 | 5.094470 | -18.962000 | 14.313000 |
| gy_dps | 5.953836 | 5.811630 | -19.687000 | 25.519000 |
| gz_dps | 23.183661 | 16.084995 | -19.977000 | 71.977000 |
| temp_c | 42.727796 | 0.014782 | 42.670000 | 42.760000 |
| accel_norm_g | 0.994175 | 0.048801 | 0.786655 | 1.182900 |

First 10-row acceleration mean: ax = 0.331800 g, ay = -0.880640 g, az = 0.227150 g.

Last 10-row acceleration mean: ax = -0.397690 g, ay = 0.914530 g, az = -0.232840 g.

Rotation observation note: the rerun shows a clear change in gravity projection across the accelerometer axes and clear gyroscope output, with gz reaching 71.977 deg/s.
