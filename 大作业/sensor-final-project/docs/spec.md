# Product Specification

## Project Title

多传感器融合扩展板设计与精度提升算法实现

## Target Indicators

| Indicator Type | Target | Verification Method | Current Status |
|---|---:|---|---|
| Static attitude precision | <= ±0.2 deg | Reference angle comparison | Pending reference-angle test |
| Dynamic attitude precision | <= ±0.5 deg | Manual tilt / dynamic response | Partially completed |
| IMU sampling rate | >= 200 Hz | ESP32 timestamp frequency test | Completed: 961.600 Hz |
| Attitude update rate | >= 100 Hz | ESP32 fusion loop frequency test | Completed: 365.227 Hz |
| Total current | <= 100 mA @ 3.3 V | Multimeter series measurement | Pending |
| PCB + BOM cost | <= 50 CNY | PCB order + BOM table | Pending |

## Hardware Scope

The expansion board is designed for ESP32-WROOM-32 and integrates IMU, magnetometer, BMP280 pressure sensor, GPS module interface, power indication LED, and 2.54 mm header connections.

## Algorithm Scope

Completed algorithms:

- Accelerometer six-position calibration
- Magnetometer hard-iron / soft-iron ellipsoid calibration
- Gyro bias and Allan variance analysis
- Complementary attitude filter
- Mahony PI attitude filter
- Low-pass and first-order Kalman denoising baseline
- 1D-CNN six-channel IMU denoising

Planned algorithms:

- Simplified ESKF attitude filter
- GPS trajectory visualization and possible multi-rate GPS/IMU fusion

## Deployment Scope

ESP32 real-time scripts currently verify sensor readout and complementary fusion loop update frequency. PC-side scripts are used for heavy offline analysis, report figures, Allan variance, and 1D-CNN training.

