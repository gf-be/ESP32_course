# Multi-Sensor Fusion ESP32 Expansion Board

## Project Overview

This project implements an ESP32-WROOM-32 compatible multi-sensor expansion board and a reproducible test workflow for sensor calibration, attitude fusion, AI denoising, and engineering performance verification.

The current hardware includes:

- ESP32-WROOM-32 development board interface
- MPU6500 / MPU6050-compatible six-axis IMU
- HMC5883L / GY-273 three-axis magnetometer
- BMP280 pressure sensor
- GPS6MV2 / NEO-6M compatible GPS module interface

## Hardware Specification

| Item | Value |
|---|---|
| Main controller | ESP32-WROOM-32 |
| IMU | MPU6500 / MPU6050-compatible, I2C address 0x68 |
| Magnetometer | HMC5883L, I2C address 0x1E |
| Pressure sensor | BMP280, I2C address 0x76 |
| GPS | GPS6MV2 / NEO-6M UART module |
| I2C pins used in tests | SDA=GPIO21, SCL=GPIO22 |
| GPS default UART pins | RX=GPIO16, TX=GPIO17 |
| Tested I2C frequency | 400 kHz |

## Software Architecture

- `firmware/drivers`: sensor scan, smoke test, GPS capture, basic data acquisition
- `firmware/calibration`: accelerometer, magnetometer, gyro Allan variance calibration scripts
- `firmware/fusion`: attitude-fusion data capture and analysis
- `firmware/ai_enhance`: 1D-CNN IMU denoising experiment
- `firmware/performance`: sampling and fusion update frequency test
- `data`: raw measured data, analysis CSV files, figures, and performance records
- `hardware`: PCB photos, schematic/PCB export placeholders, BOM file
- `docs`: specification, test report, grading standard, and report draft

## Quick Start

1. Connect the ESP32 board to the PC.
2. Open the required `pc_*.py` script in Thonny.
3. Select the local computer Python interpreter for PC-side scripts.
4. Check `COM_PORT`, GPS UART pins, and duration parameters at the top of each script.
5. Run the capture script and keep the board in the required physical state.
6. Run the corresponding `analyze_*.py` script to generate tables and figures.

## Test Results Summary

| Test | Result |
|---|---|
| I2C scan | 0x68 IMU, 0x1E HMC5883L, 0x76 BMP280 detected |
| Accelerometer six-position calibration | Average norm error reduced from 12.935 mg to 3.691 mg |
| Magnetometer ellipsoid calibration | Hard-iron center: (77.082, -94.428, -36.852) raw count |
| Gyro Allan variance | 90000 samples, 50 Hz, 1799.98 s |
| Attitude fusion | Complementary filter and Mahony PI implemented and compared |
| AI denoising | 1D-CNN reduced roll/pitch jitter to 0.0249 deg / 0.0243 deg |
| Frequency test | IMU read 961.600 Hz, fusion update 365.227 Hz |

## Current Completion Status

Completed:

- Hardware soldering and I2C bring-up
- IMU, magnetometer, BMP280 detection
- Accelerometer six-position calibration
- Magnetometer ellipsoid calibration
- Gyro bias and Allan variance analysis
- Complementary filter and Mahony PI attitude fusion
- 1D-CNN IMU denoising
- Frequency performance verification

Pending or partially complete:

- GPS outdoor track capture and folium map
- BMP280 formal pressure/altitude experiment
- Power measurement with multimeter
- Final BOM cost values
- Simplified ESKF implementation
- Demo video
- Final PDF export

## Reproducibility Notes

All raw measured CSV files are kept under `data/`. Analysis scripts generate CSV summaries and figures without modifying raw data. The PC-side scripts send temporary MicroPython code to the ESP32 through the serial port; unless explicitly stated, nothing is saved to ESP32 flash.

