# Test Report

## Hardware Bring-Up

I2C scan detected three devices:

- `0x68`: MPU6500 / MPU6050-compatible IMU
- `0x1E`: HMC5883L magnetometer
- `0x76`: BMP280 pressure sensor

BMP280 chip ID register returned `0x58`, consistent with BMP280.

## Calibration Tests

### Accelerometer Six-Position Calibration

Six static positions were collected with 1500 samples per position. Average acceleration norm error decreased from `12.935 mg` to `3.691 mg`. Maximum norm error decreased from `24.704 mg` to `5.272 mg`.

### Magnetometer Ellipsoid Calibration

The magnetometer ellipsoid dataset contains 3600 samples. Fitted hard-iron center is `(77.082, -94.428, -36.852)` raw count. Principal radii are `432.419`, `419.271`, and `409.794` raw count. Axis imbalance ratio is `1.055`.

### Gyroscope Allan Variance

The gyro Allan dataset contains 90000 samples over 1799.98 s at 50 Hz.

| Axis | Bias (deg/s) | Std (deg/s) | Min Allan (deg/s) | Tau (s) |
|---|---:|---:|---:|---:|
| X | 0.228304 | 0.052827 | 0.001481 | 157.740 |
| Y | 0.964654 | 0.071176 | 0.001963 | 106.160 |
| Z | -0.100939 | 0.060315 | 0.001939 | 36.940 |

## Attitude Fusion

Complementary filter and Mahony PI attitude fusion were compared using level static, fixed tilt, shake-return, and continuous motion datasets.

| Phase | Algorithm | Roll std (deg) | Pitch std (deg) | Yaw std (deg) |
|---|---|---:|---:|---:|
| Level static | Complementary | 1.967 | 0.931 | 8.097 |
| Level static | Mahony PI | 0.986 | 0.394 | 4.958 |
| Fixed tilt | Complementary | 0.246 | 3.699 | 10.601 |
| Fixed tilt | Mahony PI | 0.124 | 1.794 | 5.127 |

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

## Pending Tests

- GPS outdoor track and folium map
- BMP280 pressure/altitude experiment
- Power measurement
- Cost BOM finalization
- Simplified ESKF comparison

