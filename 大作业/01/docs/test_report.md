# Test Report

## Hardware Bring-Up

I2C scan detected three devices:

- `0x68`: MPU6500 / MPU6050-compatible IMU
- `0x1E`: HMC5883L magnetometer
- `0x76`: BMP280 pressure sensor

BMP280 chip ID register returned `0x58`, consistent with BMP280.

### Final PCB Bring-Up Check

The final PCB was re-tested on `COM4` on 2026-06-29. The hardware layout and module set are unchanged from the previous test board except for board size and module placement, so earlier calibration and fusion datasets remain valid for algorithm analysis. The final-board smoke test confirms that the submitted hardware is operational.

| Item | Result | Conclusion |
|---|---:|---|
| I2C scan | `0x1E`, `0x68`, `0x76` | HMC5883L, IMU, and BMP280 detected |
| IMU WHO_AM_I | `0x70` | MPU6050/MPU6500-compatible IMU readable |
| BMP280 chip ID | `0x58` | BMP280 readable |
| I2C live samples | 20 groups | ACC/GYRO/TEMP/MAG stream stable |
| GPS UART | 481 NMEA sentences, 121 valid fixes | GPS serial and fix valid |
| GPS quality | fix quality `1`, satellites `09`, HDOP `1.28`, altitude `27.1 m` | Ready for GPS trajectory experiment |

## Calibration Tests

### Accelerometer Six-Position Calibration

Six static positions were collected with 1500 samples per position. The original diagonal 6-parameter model corrected only the per-axis bias and scale, reducing the average mean-vector acceleration norm error from `12.935 mg` to `3.691 mg`. A full 12-parameter affine model was then added in the form `raw = M * true + b`, where `M` is a 3x3 scale/misalignment matrix and `b` is the three-axis bias. With this model, the average mean-vector norm error decreased to `0.755 mg`, and the maximum mean-vector norm error decreased from `24.704 mg` to `1.812 mg`.

The six source files are `pos_x_up_20260616_191706.csv`, `neg_x_up_20260616_191706.csv`, `pos_y_up_20260616_191706.csv`, `neg_y_up_20260616_191706.csv`, `pos_z_up_20260616_191706.csv`, and `neg_z_up_20260616_191706.csv`. Each posture contains 1500 static samples. The report-ready comparison figure is `data/figures/accel_6pos_12param_error_compare.png`.

| Model | Avg mean-vector norm error (mg) | Max mean-vector norm error (mg) | Sample MAE (mg) |
|---|---:|---:|---:|
| Raw | 12.935 | 24.704 | 13.421 |
| 6-parameter bias/scale | 3.691 | 5.272 | 4.891 |
| 12-parameter affine | 0.755 | 1.812 | 3.125 |

The fitted 12-parameter forward model is:

| Raw axis | true x coeff | true y coeff | true z coeff | Bias (g) |
|---|---:|---:|---:|---:|
| raw x | 0.9966041110 | -0.0796001057 | -0.0779581687 | 0.0104550107 |
| raw y | 0.0697239533 | 0.9966398483 | -0.0058036150 | 0.0087837300 |
| raw z | 0.0544679540 | -0.0059822600 | 1.0172163930 | 0.0051916032 |

For firmware use, the inverse calibration is:

| Cal axis | raw x coeff | raw y coeff | raw z coeff | Offset (g) |
|---|---:|---:|---:|---:|
| cal x | 0.9936363144 | 0.0798200426 | 0.0766064259 | -0.0114873061 |
| cal y | -0.0698260446 | 0.9977966301 | 0.0003414386 | -0.0080361168 |
| cal z | -0.0536159808 | 0.0015940015 | 0.9789750285 | -0.0045358955 |

### Magnetometer Ellipsoid Calibration

The magnetometer ellipsoid dataset contains 3600 samples. Fitted hard-iron center is `(77.082, -94.428, -36.852)` raw count. Principal radii are `432.419`, `419.271`, and `409.794` raw count. Axis imbalance ratio is `1.055`.

### Magnetometer WiFi Interference Test

A paired WiFi off/on stationary magnetometer test was collected on 2026-06-30. The source files are `mag_wifi_off_20260630_094409.csv` and `mag_wifi_on_scan_20260630_094409.csv`. Each condition contains 1200 samples over 59.95 s at 20 Hz. In the WiFi-on condition, ESP32 completed 8 WiFi scan cycles while magnetometer data were recorded.

| Indicator | WiFi off | WiFi on scan | Change |
|---|---:|---:|---:|
| Mx mean (raw count) | 173.178 | 174.195 | +1.017 |
| My mean (raw count) | 261.266 | 260.824 | -0.442 |
| Mz mean (raw count) | 165.836 | 164.262 | -1.574 |
| Field norm mean (raw count) | 354.627 | 354.057 | -0.569 |
| Field norm std (raw count) | 1.532 | 1.156 | 0.754x |
| 3-axis mean vector shift | - | - | 1.926 raw count |
| Shift relative to field norm | - | - | 0.543% |

The measured WiFi-induced magnetic shift is only `0.543%` of the stationary magnetic-field magnitude. A repeated calculation after removing the first 5 s startup transient gave a similar shift of about `0.581%`, so the result is stable. Therefore, the current GY-273 placement is considered acceptable for subsequent heading and attitude-fusion experiments. The report-ready figures are `data/figures/mag_wifi_compare_timeseries.png` and `data/figures/mag_wifi_compare_shift.png`.

### Gyroscope Allan Variance

The gyro Allan dataset contains 90000 samples over 1799.98 s at 50 Hz.

| Axis | Bias (deg/s) | Std (deg/s) | Min Allan (deg/s) | Tau (s) |
|---|---:|---:|---:|---:|
| X | 0.228304 | 0.052827 | 0.001481 | 157.740 |
| Y | 0.964654 | 0.071176 | 0.001963 | 106.160 |
| Z | -0.100939 | 0.060315 | 0.001939 | 36.940 |

## Attitude Fusion

Complementary filter, Mahony PI, and Madgwick MARG attitude fusion were compared using level static, fixed tilt, shake-return, and continuous motion datasets. The updated analysis resets the filter state at the beginning of each experimental phase and uses the 12-parameter accelerometer calibration matrix. Madgwick was configured with `beta=0.035`.

| Phase | Algorithm | Roll std (deg) | Pitch std (deg) | Yaw std (deg) |
|---|---|---:|---:|---:|
| Level static | Complementary | 0.0189 | 0.0186 | 0.0333 |
| Level static | Mahony PI | 0.0299 | 0.0280 | 0.0518 |
| Level static | Madgwick | 0.0196 | 0.0204 | 0.0394 |
| Fixed tilt | Complementary | 0.0263 | 0.0242 | 0.0868 |
| Fixed tilt | Mahony PI | 0.0385 | 0.0350 | 0.1263 |
| Fixed tilt | Madgwick | 0.0709 | 0.0643 | 0.1002 |

The Madgwick result is close to the complementary filter in the level-static case and has a lower fixed-tilt yaw standard deviation than Mahony PI in this dataset. Its roll/pitch jitter under fixed tilt is larger than the other two algorithms, which indicates that the `beta` parameter and magnetometer weighting still need tuning for stronger tilt conditions. The current result is nevertheless stable enough to support the report requirement of implementing an additional quaternion-based attitude fusion algorithm.

## AI Denoising

1D-CNN denoising was trained with six-channel windows: `ax, ay, az, gx, gy, gz`. Compared methods include raw signal, low-pass filter, first-order Kalman filter, and 1D-CNN.

| Method | Roll jitter std (deg) | Pitch jitter std (deg) |
|---|---:|---:|
| Raw | 0.1250 | 0.1257 |
| Low-pass | 0.0313 | 0.0314 |
| Kalman | 0.0521 | 0.0528 |
| 1D-CNN | 0.0249 | 0.0243 |

## Frequency Performance

| Indicator | Measured | Target | Result |
|---|---:|---:|---|
| IMU read frequency | 961.600 Hz | >= 200 Hz | Pass |
| Fusion update frequency | 365.227 Hz | >= 100 Hz | Pass |
| Offline complementary update throughput | 363093 Hz | >= 100 Hz | Pass |
| Offline Mahony update throughput | 193657 Hz | >= 100 Hz | Pass |
| Offline Madgwick update throughput | 37846 Hz | >= 100 Hz | Pass |

## GPS Outdoor Track

The grading requirement lists GPS trajectory overlay as a required data visualization item. A final outdoor walking dataset was collected on 2026-07-01 with the ESP32 powered by a power bank. The ESP32 program saved synchronized IMU, magnetometer, and GPS rows under `/imu_gps_logs`, and a phone GNSS GPX track was recorded at the same time as a spatial reference. The phone GPX export contains invalid absolute timestamps, so it is used for spatial overlay and nearest-distance comparison rather than strict time synchronization.

| Indicator | Phone GNSS Reference | ESP32 GPS Quality Filtered |
|---|---:|---:|
| Track points | 439 | 1116 |
| Track distance | 770.15 m calculated / 788.09 m GPX extension | 632.48 m |
| Median satellites | - | 6 |
| Median HDOP | - | 1.64 |
| Nearest-distance median to phone track | - | 2.80 m |
| Nearest-distance P90 to phone track | - | 14.18 m |
| Nearest-distance P95 to phone track | - | 15.75 m |

The ESP32 GNSS trajectory agrees with the phone reference at the several-meter to ten-meter level on the overlapping route. Therefore, this dataset is suitable for the required GPS trajectory visualization and for the subsequent GPS/IMU fusion experiment. The report-ready outputs are `data/figures/gps_phone_esp32_eskf_overlay_20260701_223520.png` and `data/figures/gps_phone_esp32_eskf_overlay_20260701_223520.html`.

## Simplified 15D ESKF

An offline 15-state simplified error-state Kalman filter was implemented with

`dx = [dp, dv, dtheta, dbg, dba]^T`.

For the final outdoor dataset, synchronized IMU/GPS rows are available. The actual flash-logging rate is about 7.84 Hz, so an unconstrained inertial prediction drifts quickly and the original strict-gate ESKF rejected many GPS observations. According to the measured hardware sampling condition and the low-speed walking application scenario, the final method is therefore defined as a low-speed loose-coupled 15D ESKF rather than a data-fitted special case: IMU data provide attitude and short-term prediction, GPS position provides the dominant long-term correction, and GPS position differences provide pseudo velocity updates when consecutive fixes are valid.

| Indicator | ESP32 GPS Raw | Robust 15D ESKF |
|---|---:|---:|
| Points/states | 1116 | 5975 |
| Track distance | 632.48 m | 912.85 m |
| Nearest distance to phone, median | 2.80 m | 4.88 m |
| Nearest distance to phone, P90 | 14.18 m | 13.20 m |
| Nearest distance to phone, P95 | 15.75 m | 15.37 m |
| Position updates | - | 1116 |
| Pseudo velocity updates | - | 475 |
| Position innovation median | - | 0.32 m |
| Position innovation P95 | - | 2.34 m |

The low-speed loose-coupled ESKF no longer rejects valid GPS fixes; instead, it accepts all 1116 usable position updates and performs 475 GPS-difference velocity updates. Its median nearest distance is slightly larger than raw GPS because the state trajectory includes IMU-propagated intermediate samples, while the P90/P95 spatial consistency is slightly improved. This result supports the course requirement of implementing a simplified 15D ESKF with real synchronized GPS/IMU data under the actual ESP32 logging condition. The report-ready outputs are `data/analysis/eskf_15d_sync_robust_states_20260701_223520.csv`, `data/figures/gps_phone_esp32_eskf_overlay_20260701_223520.png`, and `data/figures/eskf_15d_sync_robust_innovation_20260701_223520.png`.

### ESP32 Real-Time 15D ESKF Firmware

An ESP32 MicroPython real-time 15D simplified ESKF program has been prepared. It reads IMU, magnetometer, and GPS data on the board, maintains the nominal state `p, v, q, bg, ba`, and prints `ESKF15` CSV records through the serial port for live capture. The program is ready to install as `/main.py`; on first installation the existing board-side `/main.py` is preserved as `/main_before_eskf.py`.

| File | Purpose |
|---|---|
| `firmware/fusion/esp32_eskf_15d_realtime_main.py` | ESP32 real-time ESKF firmware |
| `firmware/tools/pc_install_esp32_eskf_15d.py` | Install firmware to ESP32 `/main.py` |
| `firmware/fusion/pc_eskf_15d_realtime_capture.py` | Capture live `ESKF15` serial records to CSV |
| `firmware/fusion/pc_eskf_15d_serial_web.py` | Use the PC browser as a real-time ESKF display |
| `firmware/fusion/analyze_eskf_15d_realtime.py` | Generate real-time ESKF summary table and figures |

The real-time firmware targets a 100 Hz onboard ESKF loop and prints compact serial records at 5 Hz. The actual loop rate is written to the `imu_hz` field and should be reported from measured data after outdoor testing. The browser dashboard is only a display terminal; sensor reading and ESKF computation remain on ESP32.

## Pending Tests

- BMP280 pressure/altitude experiment
- Power measurement
- Cost BOM finalization
