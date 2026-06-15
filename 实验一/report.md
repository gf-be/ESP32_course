---
title: "实验一 开发环境安装与传感器特性分析"
author: "学院：人工智能与交通工程学院　姓名：罗丹　学号：2251801014"
date: "2026-05-26"
lang: zh-CN
---

# 实验一 开发环境安装与传感器特性分析

| 项目 | 信息 |
|---|---|
| 学院 | 人工智能与交通工程学院 |
| 姓名 | 罗丹 |
| 学号 | 2251801014 |
| 日期 | 2026-05-26 |

## 摘要

本实验完成了 Thonny + ESP32 MicroPython 开发环境检查、ESP32-S3 串口连接、示例程序测试、片内温度传感器 10 Hz 连续采集、CSV 数据保存，以及基于 Allan 方差的温度传感器特性分析。正式采集共获得 18000 条温度数据，实际采集时长 1799.893 s，满足 0.5 小时采集要求。实验过程中使用温枪对 ESP32 板进行加热，温度从稳定段约 32 ℃ 上升至最高 59 ℃，温度扰动对 Allan 方差曲线产生明显影响。

由于温枪实际加热和停止加热后的热恢复都属于非平稳过程，本文将全程 Allan 方差图用于展示温度扰动影响；同时选取加热前稳定段 0-392 s 估计稳定状态噪声参数。该稳定段 Allan deviation 最小值约为 0.0670 ℃，对应平均时间 tau 为 2.6 s；随机游走系数约为 0.03118 ℃/√s。

## 1. 实验目的与任务

### 1.1 实验目的

1. 掌握 ESP32 开发平台的开发环境安装、调试、下载和测试方法。
2. 掌握 Thonny + ESP32 MicroPython 环境下的程序开发和运行流程。
3. 通过片内温度传感器数据采集和 Allan 方差分析，理解温度传感器的噪声、漂移和热扰动特性。

### 1.2 实验任务

1. 完成 Thonny + ESP32 MicroPython 环境安装，详细记录安装过程中的问题和解决方案。
2. 下载或参考官方 SAMPLES 示例程序，完成 `blink.py` 和 `hello_world.py` 的下载测试。
3. 连接片内温度传感器，实现每秒 10 次数据读取，并在终端显示 `时间：温度 (℃)`。
4. 连续采集 0.5 小时温度数据，保存为 CSV 格式文件。
5. 编写 Python 脚本对采集数据进行 Allan 方差分析，绘制 Allan 方差 log-log 图，标注不同噪声成分对应斜率，并提取零偏不稳定性和随机游走类参数。
6. 选做：用温枪对传感器进行加热，分析温度变化对 Allan 方差的影响。

## 2. 实验环境与材料

| 项目 | 内容 |
|---|---|
| 主机系统 | Windows |
| 开发板 | ESP32-S3 开发板 |
| USB 串口 | USB 串行设备 |
| ESP32 串口 | COM10 |
| MicroPython 固件 | v1.28.0 on 2026-04-06 |
| MicroPython 构建 | ESP32_GENERIC_S3 |
| Python | Python 3.12.7 |
| PC 端工具 | Thonny 5.0.0、esptool 5.2.0、mpremote 1.28.0 |
| Python 分析库 | numpy、pandas、matplotlib、pyserial |
| 传感器 | ESP32-S3 片内温度传感器 |
| 加热工具 | 温枪 |

## 3. 开发环境安装与问题处理

### 3.1 工具安装与验证

本实验使用如下命令安装或确认 PC 端工具：

```powershell
python -m pip install --user thonny esptool mpremote
```

安装后工具版本如下：

| 工具 | 版本 | 用途 |
|---|---:|---|
| Thonny | 5.0.0 | MicroPython IDE |
| esptool | 5.2.0 | ESP32 固件擦除与写入 |
| mpremote | 1.28.0 | 命令行连接 MicroPython 板卡 |

安装过程中发现用户脚本目录未加入 PATH，直接输入 `mpremote` 或 `esptool` 可能不可用。解决方法是使用模块方式运行：

```powershell
python -m esptool
python -m mpremote
python -m thonny
```

### 3.2 串口识别

插入开发板后，系统识别到 ESP32 串口：

```text
USB 串行设备 (COM10)
```

`COM4` 和 `COM7` 为蓝牙串口，不作为 ESP32 通信端口。本实验使用 `COM10` 连接开发板。

### 3.3 固件与温度 API

开发板固件验证结果如下：

```text
MicroPython v1.28.0 on 2026-04-06
machine='Generic ESP32S3 module with ESP32S3'
esp32.mcu_temperature: available
temperature: 31
```

本固件提供 `esp32.mcu_temperature()`，可直接读取片内温度传感器的摄氏温度。若使用旧固件且缺少该 API，需要刷写新版 ESP32-S3 MicroPython 固件，否则无法完成片内温度采集任务。

## 4. 官方 SAMPLES 示例程序测试

本实验的示例程序参考 MicroPython 官方 ESP32 文档中的基础板级控制、GPIO、计时和 NeoPixel 示例。由于本次使用的 ESP32-S3 开发板板载灯不是普通 GPIO2 LED，而是连接在 GPIO48 的单颗 NeoPixel RGB LED，因此 `blink.py` 保留官方 blink 示例“周期性控制板载 LED 亮灭”的功能目标，并按实际板卡硬件适配为 GPIO48 + NeoPixel 驱动。

提交包中的 `code/` 目录作为本实验 SAMPLES 目录，保存 `hello_world.py`、`blink.py` 和适配说明。

| 示例文件 | 来源/依据 | 本板适配说明 | 测试结果 |
|---|---|---|---|
| `code/hello_world.py` | MicroPython 官方基础板级控制示例思路 | 无需特殊硬件适配 | 运行成功 |
| `code/blink.py` | MicroPython 官方 GPIO/NeoPixel 控制示例思路 | 本板板载 RGB LED 为 `NeoPixel(Pin(48), 1)`，使用 GPIO48 | 运行成功，RGB 灯闪烁 12 次 |

### 4.1 hello_world 测试

运行命令：

```powershell
python -m mpremote connect COM10 run .\code\hello_world.py
```

运行输出：

```text
hello_world.py running on ESP32 MicroPython
platform: esp32
freq_hz: 160000000
unique_id: a4cb8fd8c568
```

### 4.2 blink 测试

运行命令：

```powershell
python -m mpremote connect COM10 run .\code\blink.py
```

运行输出：

```text
blink.py started; RGB_PIN = 48
blink step 0
blink step 1
...
blink step 11
blink.py done
```

测试中 RGB 灯按 0.5 s 周期亮灭，程序完成 12 次切换后自动退出，说明示例程序下载和板端执行正常。

## 5. 温度数据采集

### 5.1 采集程序

采集脚本为 `code/temp_logger_10hz.py`。核心设置如下：

```python
SAMPLE_HZ = 10
DURATION_S = 30 * 60
OUTPUT_FILE = "temp_data.csv"
```

脚本每 0.1 s 读取一次 `esp32.mcu_temperature()`，终端输出：

```text
时间：x.xxxs 温度：yy.yy ℃
```

同时在 ESP32 文件系统中写入 CSV 文件 `temp_data.csv`，字段为：

```text
sample,elapsed_s,temp_c
```

### 5.2 采集结果

正式采集启动时间为 2026-05-26 15:29:28。结果如下：

| 项目 | 数值 |
|---|---:|
| 样本数 | 18000 |
| 采样周期 | 0.100000 s |
| 采样频率 | 10 Hz |
| 首个时间戳 | 0.007 s |
| 最后时间戳 | 1799.900 s |
| 实际时长 | 1799.893 s |
| 最低温度 | 31.0 ℃ |
| 最高温度 | 59.0 ℃ |
| 全程平均温度 | 37.877 ℃ |

原始数据文件见 `data/temp_data.csv`。

## 6. Allan 方差分析方法

Allan 方差常用于分析传感器输出中的随机噪声和低频漂移。设温度序列为 \(y_i\)，采样周期为 \(T_s\)。当聚类长度为 \(m\) 时，平均时间为：

\[
\tau=mT_s
\]

将数据按每 \(m\) 个样本分组，计算每组均值 \(\bar{y}_k\)，Allan 方差为：

\[
\sigma_A^2(\tau)=\frac{1}{2}\left<(\bar{y}_{k+1}-\bar{y}_k)^2\right>
\]

Allan deviation 为：

\[
\sigma_A(\tau)=\sqrt{\sigma_A^2(\tau)}
\]

在 log-log 图中，不同噪声成分具有不同典型斜率：

| 斜率 | 常见含义 | 本实验解释 |
|---:|---|---|
| -1/2 | 白噪声 | 短时间平均可以降低随机抖动 |
| 0 | 零偏不稳定性 | Allan deviation 出现平台或最小区域 |
| +1/2 | 随机游走 | 长时间低频漂移开始主导 |

本实验 Allan 图中绘制了 -1/2、0、+1/2 三类参考斜率线，用于辅助判断噪声成分。由于 ESP32-S3 的 `mcu_temperature()` 返回整数摄氏度，温度数据存在 1 ℃ 量化台阶，因此提取参数会受量化分辨率影响。

## 7. 全程温度曲线与温枪事件

实验过程中使用温枪对 ESP32 板进行加热，人工记录的加热时间约为 2026-05-26 15:36 到 15:41。采集启动时间为 15:29:28，因此实际加温区间约对应采集时间 392-692 s。温枪停止后，芯片温度仍继续上升并在 794.3 s 达到 59 ℃峰值，随后逐步下降；这部分属于停止加热后的热惯性和散热恢复过程。

![全程温度曲线](assets/temperature_time_series.png)

从温度曲线可以看出：

1. 0-392 s 为相对稳定初始段，温度主要在 31-33 ℃。
2. 392-692 s 为实际温枪加温区间，温度从约 33 ℃上升到约 42 ℃。
3. 停止加温后温度继续上升，峰值为 59 ℃，出现在 794.3 s。
4. 692-1235 s 主要表现为热惯性和散热恢复过程，温度从高位逐步下降。
5. 1235 s 后温度稳定在约 34-36 ℃，高于实验最初的 31-33 ℃。

分段统计如下：

| 分段 | 时间范围 | 样本数 | 平均温度 | 中位温度 | 标准差 | 最小值 | 最大值 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 加热前 | 0.007-391.900 s | 3920 | 32.144 ℃ | 32.0 ℃ | 0.706 ℃ | 31.0 ℃ | 33.0 ℃ |
| 实际加温 | 392.001-692.000 s | 3001 | 37.047 ℃ | 37.0 ℃ | 3.522 ℃ | 32.0 ℃ | 42.0 ℃ |
| 热恢复 | 692.100-1235.000 s | 5430 | 46.218 ℃ | 46.0 ℃ | 6.933 ℃ | 36.0 ℃ | 59.0 ℃ |
| 恢复后 | 1235.100-1799.900 s | 5649 | 34.280 ℃ | 34.0 ℃ | 0.498 ℃ | 34.0 ℃ | 36.0 ℃ |

相对稳定初始段中位温度 32 ℃，温枪使片内温度最高升高约 27 ℃。

## 8. Allan 方差结果

### 8.1 全程 Allan deviation

全程数据包含实际温枪加热和停止加热后的散热恢复过程，属于非平稳数据。全程 Allan 图适合展示热扰动影响，不适合直接作为稳定噪声参数估计依据。

![全程 Allan deviation](assets/allan_temperature_full.png)

全程数据参数：

| 项目 | 数值 |
|---|---:|
| 样本数 | 18000 |
| 采样周期 | 0.100000 s |
| Allan deviation 最小值 | 0.1068 ℃ |
| 对应 tau | 0.8 s |
| 随机游走系数 | 0.10279 ℃/√s |

全程随机游走类参数明显受到温枪加热和冷却趋势影响，因此不能直接代表传感器稳定工作时的随机游走。

### 8.2 稳定初始段 Allan deviation

为估计稳定状态下的传感器噪声参数，选取 0-392 s 作为稳定初始段。该段温度范围为 31.0-33.0 ℃，不包含温枪加热过程。

![稳定初始段 Allan deviation](assets/allan_temperature_stable_pre.png)

稳定初始段参数：

| 项目 | 数值 |
|---|---:|
| 样本数 | 3920 |
| 时长 | 391.893 s |
| 温度范围 | 31.0-33.0 ℃ |
| 平均温度 | 32.144 ℃ |
| Allan deviation 最小值 | 0.0670 ℃ |
| 对应 tau | 2.6 s |
| 随机游走系数 | 0.03118 ℃/√s |
| 速率随机游走类换算系数 | 0.05401 ℃/√s |

因此，本实验将稳定初始段 Allan deviation 最小值 0.0670 ℃ 作为温度传感器零偏不稳定性的近似量，将 0.03118 ℃/√s 作为随机游走类参数。

### 8.3 分段 Allan deviation 对比

![分段 Allan deviation](assets/allan_temperature_segments.png)

分段 Allan 图显示：

1. 加热前稳定段曲线整体较低，代表相对稳定温度条件下的噪声水平。
2. 实际加温和热恢复曲线在中长 tau 区间明显抬升，说明温度变化趋势主导了 Allan 方差。
3. 恢复后曲线回落，但仍反映芯片热恢复后的新稳定温度状态。

## 9. 温枪加热影响分析

温枪加热对 ESP32 片内温度读数影响显著。稳定初始段中位温度约为 32 ℃；实际加温区间为 392-692 s，温度从约 33 ℃升至约 42 ℃。温枪停止后，芯片内部温度由于热惯性继续升高，并在 794.3 s 达到 59 ℃，相对稳定初始段升高约 27 ℃。之后温度逐步下降，经历明显的散热回落过程。

从 Allan 方差角度看，实际加温和停止加温后的热恢复都会引入强低频趋势，使 Allan deviation 在中长平均时间上升。如果直接使用全程数据提取零偏不稳定性和随机游走参数，会把外部温度扰动误认为传感器自身漂移，导致参数偏大。因此，稳定噪声参数应从温度相对稳定的区间提取；实际加温区间和热恢复区间应作为外部环境扰动单独分析。

本实验说明：温度变化会显著改变片内温度序列的统计特性，使 Allan 方差曲线在较大 tau 区间抬升。在实际传感器建模中，应记录温度环境或剔除明显加热、冷却过程。

## 10. 结论

1. Thonny + ESP32 MicroPython 开发环境可正常使用，ESP32-S3 通过 `COM10` 连接。
2. MicroPython 固件为 v1.28.0，`esp32.mcu_temperature()` 可正常读取片内温度。
3. `hello_world.py` 和 `blink.py` 均已在板端运行成功。
4. 温度采集程序完成 10 Hz、0.5 小时连续采样，获得 18000 条 CSV 数据。
5. 稳定初始段 Allan deviation 最小值约为 0.0670 ℃，对应 tau 为 2.6 s；随机游走系数约为 0.03118 ℃/√s。
6. 温枪实际加温约 5 分钟，停止加温后片内温度继续升至最高 59 ℃，相对稳定初始段中位温度升高约 27 ℃。
7. 热扰动会显著放大 Allan 方差中的低频成分，因此全程 Allan 参数不能直接代表稳定噪声参数。

## 11. 实验任务逐项核对

| 实验要求 | 完成情况 | 证据文件/结果 |
|---|---|---|
| 1）完成 Thonny + ESP32 MicroPython 环境安装，详细记录问题和解决方案 | 已完成 | 报告第 3 节记录安装、PATH 问题、串口识别、温度 API 验证 |
| 2）下载官方 SAMPLES 示例程序，完成 `blink.py` 和 `hello_world.py` 下载测试 | 已完成 | 报告第 4 节；`code/hello_world.py` 和 `code/blink.py`；在 COM10 上运行成功 |
| 3）连接片内温度传感器，10 Hz 读取并终端显示，连续 0.5 小时保存 CSV | 已完成 | `code/temp_logger_10hz.py`；`data/temp_data.csv`，18000 条，1799.893 s |
| 4）编写 Python 脚本做 Allan 方差分析，绘制 log-log 图并标注噪声斜率，提取参数 | 已完成 | `code/allan_temperature.py`；全程和稳定段 Allan 图；零偏不稳定性约 0.0670 ℃，随机游走系数约 0.03118 ℃/√s |
| 5）选做：温枪加热并分析温度变化对 Allan 方差的影响 | 已完成 | `assets/temperature_time_series.png`、`assets/allan_temperature_segments.png`；实际加温区间 392-692 s，峰值 59 ℃ |

## 12. 提交文件说明

| 文件或目录 | 内容 |
|---|---|
| `report.md` | 本中文 Markdown 实验报告 |
| `index.html` | 可直接浏览的网页版本 |
| `data/temp_data.csv` | 30 分钟 10 Hz 原始温度数据 |
| `data/temperature_event_segments.csv` | 加热前、实际加温、热恢复、恢复后的分段统计 |
| `data/allan_temperature_summary.csv` | 全程 Allan deviation 数据表 |
| `data/stable_pre_0_392s_allan_metrics.txt` | 稳定初始段 Allan 参数 |
| `assets/temperature_time_series.png` | 温度时间曲线 |
| `assets/allan_temperature_full.png` | 全程 Allan deviation 图 |
| `assets/allan_temperature_segments.png` | 分段 Allan deviation 对比图 |
| `assets/allan_temperature_stable_pre.png` | 稳定初始段 Allan deviation 图 |
| `code/hello_world.py` | MicroPython hello world 示例 |
| `code/blink.py` | 本板实际测试使用的 blink 示例 |
| `code/blink_rgb_esp32s3.py` | ESP32-S3 GPIO48 RGB 闪灯示例 |
| `code/temp_logger_10hz.py` | ESP32 温度采集程序 |
| `code/allan_temperature.py` | PC 端 Allan 方差分析脚本 |
| `code/SAMPLES_README.md` | 官方 SAMPLES 来源与本板适配说明 |

## 13. 参考资料

1. MicroPython ESP32 官方文档：<https://docs.micropython.org/en/latest/esp32/>
2. MicroPython ESP32-S3 固件下载页：<https://www.micropython.org/download/ESP32_GENERIC_S3/>
3. MicroPython mpremote 文档：<https://docs.micropython.org/en/latest/reference/mpremote.html>
4. Thonny MicroPython 使用说明：<https://github.com/thonny/thonny/wiki/MicroPython>

