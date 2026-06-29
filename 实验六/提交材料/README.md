# 实验六：BMP280 气压测高与高度融合

本目录为实验六最终提交材料，保留报告、采集数据、图表和可复现实验代码。

## 文件结构

```text
.
├── assets/                 # 报告图表
├── code/                   # ESP32 采集代码与 PC 端分析代码
├── data/                   # 原始数据与分析汇总表
├── report_lab6_final.pdf   # 最终报告
├── report_lab6_final.tex   # LaTeX 源文件
├── requirements.txt        # Python 依赖
└── README.md               # 提交说明
```

## 代码说明

- `code/esp32_bmp280_staircase_main.py`：ESP32 端 BMP280 楼梯/楼层离线采集程序，每层按一次 BOOT 后采样并保存 CSV。
- `code/esp32_gps_baro_fusion.py`：ESP32 端 GPS 与 BMP280 同步采集及互补滤波程序，每次运行生成新 CSV。
- `code/analyze_bmp280_staircase.py`：PC 端楼梯实验分析脚本，生成楼层均值表、回归指标和气压/高度图。
- `code/analyze_gps_baro_fusion.py`：PC 端 GPS/气压融合分析脚本，生成融合指标表和对比图。
- `code/build_lab6_report.py`：重新生成图表并编译 LaTeX 报告。

## 复现实验结果

安装依赖后，在本目录运行：

```bash
python code/analyze_bmp280_staircase.py
python code/analyze_gps_baro_fusion.py
```

如需重新编译报告：

```bash
python code/build_lab6_report.py
```

## 数据与结果

- 楼梯实验原始数据：`data/staircase_esp32_0003.csv`
- GPS/气压融合原始数据：`data/gps_baro_0005.csv`
- 楼梯实验线性回归：气压-楼层关系 `R^2 = 0.997979`，相对高度-楼层关系 `R^2 = 0.997990`
- GPS/气压融合：GPS 有效样本 4499 个，校正后融合高度标准差约 `0.286 m`
