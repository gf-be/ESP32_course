# ESP32 实时 15 维简化 ESKF 使用说明

## 功能说明

实时版程序运行在 ESP32 MicroPython 上，读取：

- MPU6050/MPU6500 加速度计、陀螺仪；
- HMC5883L 磁力计；
- GPS6MV2/NEO-6M NMEA 数据。

程序实时维护 15 维误差状态：

```text
delta x = [delta p, delta v, delta theta, delta bg, delta ba]^T
```

名义状态为：

```text
x = [p, v, q, bg, ba]
```

其中 IMU/MAG 用于姿态和高频预测，GPS 用于位置观测更新。串口会持续输出 `ESKF15,...` 数据行，电脑端采集脚本可保存为 CSV。

程序主循环目标频率为 100 Hz，串口记录输出频率为 5 Hz。CSV 中的 `imu_hz` 字段是 ESP32 端实际测得的循环频率，因此论文中应使用实测值评价实时性。

## 文件

ESP32 主程序：

`F:\mechineSight\stm32\罗丹\大作业\sensor-final-project\firmware\fusion\esp32_eskf_15d_realtime_main.py`

安装脚本：

`F:\mechineSight\stm32\罗丹\大作业\sensor-final-project\firmware\tools\pc_install_esp32_eskf_15d.py`

电脑端实时保存脚本：

`F:\mechineSight\stm32\罗丹\大作业\sensor-final-project\firmware\fusion\pc_eskf_15d_realtime_capture.py`

电脑端实时网页显示脚本：

`F:\mechineSight\stm32\罗丹\大作业\sensor-final-project\firmware\fusion\pc_eskf_15d_serial_web.py`

采集后分析脚本：

`F:\mechineSight\stm32\罗丹\大作业\sensor-final-project\firmware\fusion\analyze_eskf_15d_realtime.py`

## 安装方法

注意：安装脚本会把实时 ESKF 程序写入 ESP32 的 `/main.py`。如果板子里原来已有 `/main.py`，首次安装时会先改名保存为 `/main_before_eskf.py`，再写入实时 ESKF 程序。

1. 关闭 Thonny Shell，避免占用 `COM4`。
2. 确认 ESP32 插在 `COM4`。
3. 在电脑端运行：

```text
F:\mechineSight\stm32\罗丹\大作业\sensor-final-project\firmware\tools\pc_install_esp32_eskf_15d.py
```

安装完成后 ESP32 复位，上电会自动运行实时 ESKF。

## 实时观察

串口输出包含两类行：

```text
ESKF15_HEADER,...
ESKF15,...
```

其中 `initialized=0` 表示尚未拿到可用 GPS 原点；`initialized=1` 表示已经建立 ENU 局部坐标并开始 ESKF 实时更新。

LED 状态：

- 每 3 秒短闪：等待 GPS 或尚未初始化；
- 1 Hz 慢闪：收到 GPS 但暂未满足质量条件；
- 每 2 秒双闪：GPS 可用且 ESKF 正在更新；
- 快闪：程序异常。

## 电脑保存实时数据

如果只想保存 CSV，关闭 Thonny Shell 后运行：

```text
F:\mechineSight\stm32\罗丹\大作业\sensor-final-project\firmware\fusion\pc_eskf_15d_realtime_capture.py
```

如果想把电脑作为“显示屏”，运行：

```text
F:\mechineSight\stm32\罗丹\大作业\sensor-final-project\firmware\fusion\pc_eskf_15d_serial_web.py
```

浏览器打开 `http://127.0.0.1:8767` 后，可以实时观察姿态板、ENU 轨迹、GPS 定位状态、创新量、协方差和 ESP32 实测循环频率。该脚本也会同步保存 `ESKF15` 数据 CSV。

默认采集 600 s，输出目录为：

```text
F:\mechineSight\stm32\罗丹\大作业\sensor-final-project\data\fusion_comparison\eskf_realtime
```

采集完成后运行分析脚本：

```text
F:\mechineSight\stm32\罗丹\大作业\sensor-final-project\firmware\fusion\analyze_eskf_15d_realtime.py
```

分析脚本会自动读取最新的 `eskf15_realtime_*.csv`，并输出：

- `data\analysis\eskf_15d_realtime_summary_*.csv`：实时 ESKF 指标表；
- `data\figures\eskf_15d_realtime_track_*.png`：GPS、ESKF、手机 GNSS 参考轨迹叠加图；
- `data\figures\eskf_15d_realtime_error_*.png`：创新量、协方差和实时循环频率曲线。

## 实验建议

为了让实时 ESKF 数据更可信，建议户外开阔环境下采集：

1. 上电后静止 30-60 s，等待 GPS 定位和姿态稳定；
2. 板子方向尽量固定，GPS 天线朝上；
3. 步行 5-10 min，包含直线、转弯、短暂停；
4. 手机同时记录 GPX 轨迹作为参考；
5. 回来后用电脑端脚本保存 CSV，再进行轨迹和误差分析。

## 论文口径

这一版可写为“ESP32 端实时 15 维简化 ESKF 工程实现”。如果采集到同步实时 CSV，可进一步分析：

- 实时 ESKF 更新频率；
- GPS 更新次数和拒绝次数；
- GPS 原始轨迹、实时 ESKF 轨迹、手机 GNSS 参考轨迹对比；
- 创新量和协方差变化；
- 与离线 ESKF 结果对比。

需要注意：由于板子朝向、手持运动和 GPS 遮挡会影响实时融合效果，报告中应强调这是低成本传感器平台上的工程实现，不应把 GPS6MV2/NEO-6M 的定位结果描述为高精度真值。
