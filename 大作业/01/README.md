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
- `hardware`: schematic PDF, PCB PDF, Gerber files, BOM, and hardware photos
- `docs`: specification, test report, grading standard, and report draft

## Quick Start

1. Connect the ESP32 board to the PC.
2. Open the required `pc_*.py` script in Thonny.
3. Select the local computer Python interpreter for PC-side scripts.
4. Check `COM_PORT`, GPS UART pins, and duration parameters at the top of each script.
5. Run the capture script and keep the board in the required physical state.
6. Run the corresponding `analyze_*.py` script to generate tables and figures.

## Live Demo

For an in-person project demonstration, install or keep the ESP32 real-time 15D ESKF firmware as `/main.py`, then run:

`firmware/fusion/pc_eskf_15d_serial_web.py`

Open `http://127.0.0.1:8767` in the browser. The dashboard reads COM4 directly, visualizes attitude, GPS status, raw GPS trajectory, ESKF fused trajectory, innovation, uncertainty, and saves live CSV records under `data/fusion_comparison/eskf_realtime/`. ECharts is served locally from `firmware/fusion/assets/echarts.min.js`, so the dashboard can run without Internet access after the Python server starts.

The recommended demonstration flow is documented in `docs/demo_guide.md`.

## Test Results Summary

| Test | Result |
|---|---|
| I2C scan | 0x68 IMU, 0x1E HMC5883L, 0x76 BMP280 detected |
| Accelerometer six-position calibration | 12-parameter model reduced average mean-vector norm error from 12.935 mg to 0.755 mg |
| Magnetometer ellipsoid calibration | Hard-iron center: (77.082, -94.428, -36.852) raw count |
| Gyro Allan variance | 90000 samples, 50 Hz, 1799.98 s |
| Attitude fusion | Complementary, Mahony PI, and Madgwick MARG implemented and compared |
| AI denoising | 1D-CNN reduced roll/pitch jitter to 0.0249 deg / 0.0243 deg |
| Frequency test | IMU read 961.600 Hz, fusion update 365.227 Hz |
| GPS trajectory overlay | Phone GPX and ESP32 GPS overlap with 2.80 m median nearest distance |
| Simplified 15D ESKF | Low-speed loose-coupled 15D ESKF with 1116 GPS position updates and 475 pseudo velocity updates |

## Current Completion Status

Completed:

- Hardware soldering and I2C bring-up
- IMU, magnetometer, BMP280 detection
- Accelerometer six-position calibration
- Magnetometer ellipsoid calibration
- Gyro bias and Allan variance analysis
- Complementary filter and Mahony PI attitude fusion
- Madgwick MARG attitude fusion
- 1D-CNN IMU denoising
- Frequency performance verification
- GPS outdoor trajectory capture with phone GNSS reference
- Folium GPS trajectory overlay map
- ESP32 power-bank offline IMU/GPS logger
- Low-speed walking 15D loose-coupled ESKF post-processing

Submission notes:

- BMP280 pressure/altitude analysis files are archived under `data/analysis/` and `data/figures/`.
- Power measurement is documented in the report as an engineering estimate because the current PCB revision does not reserve a current-test jumper or shunt resistor.
- `hardware/BOM.csv` contains the merged EDA BOM and cost-supplement table; `hardware/BOM_merged.xlsx` is kept for manual review.
- Demo video is not included because the instructor confirmed it is optional for this submission.
- Final PDF report will be added manually as `docs/final_report.pdf` after Word layout is finalized.

## Reproducibility Notes

All raw measured CSV files are kept under `data/`. Analysis scripts generate CSV summaries and figures without modifying raw data. Most PC-side scripts send temporary MicroPython code to the ESP32 through the serial port; the outdoor GPS/IMU logger is an exception and is installed as ESP32 `/main.py` so it can run from a power bank and save logs under `/imu_gps_logs`. The GPS/IMU fusion result is reported as a 15-state loose-coupled ESKF designed according to the measured hardware sampling condition and the low-speed walking application scenario.
