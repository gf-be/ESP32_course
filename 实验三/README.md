# 实验三 GNSS 模块驱动与高精度定位

姓名：罗丹  
学号：2251801014

本仓库为实验三最终提交包，使用 **ESP32 + GNSS 模块 + MicroPython + Python 后处理** 完成 NMEA 解析、WiFi 上传、户外采集、folium 可视化、手机参考轨迹对比、室内外定位质量统计和实时 Web 可视化回放。

GitHub 仓库链接：https://github.com/gf-be/ESP32_course

## 目录结构

```text
.
├── report_lab3_final.pdf          # 最终实验报告
├── report_lab3_final.tex          # LaTeX 源码
├── requirements.txt               # Python 依赖
├── code/                          # ESP32 与电脑端代码
├── data/                          # 必要实测数据与分析结果
├── assets/                        # 报告图片
└── 实验三GitHub提交内容.md          # 提交内容说明
```

## 关键代码

| 文件 | 说明 |
|---|---|
| `code/gnss_nmea.py` | 自写 NMEA 解析器 |
| `code/01_gnss_nmea_smoke.py` | 串口接收与原始 NMEA 验证 |
| `code/02_test_gnss_parser.py` | NMEA 解析器单元测试 |
| `code/03_wifi_udp_track.py` | ESP32 WiFi UDP 上传 |
| `code/04_serial_track_logger.py` | 串口记录备用脚本 |
| `code/05_flash_track_logger.py` | ESP32 Flash 离线采集脚本 |
| `code/receiver.py` | 电脑端 UDP 接收并保存 CSV |
| `code/plot_track.py` | folium 地图与定位质量统计图 |
| `code/compare_esp_phone.py` | ESP32 与手机参考轨迹对比 |
| `code/compare_environment_quality.py` | 室内外定位质量统计 |
| `code/realtime_web_visualizer.py` | Flask + WebSocket + Leaflet 实时回放 |
| `code/config_wifi.py.example` | WiFi 配置模板，不含真实密码 |

## 实测数据

| 文件 | 说明 |
|---|---|
| `data/track_flash_outdoor_001.csv` | 户外主实验数据，1051 点 |
| `data/track_20260605_212206.csv` | WiFi UDP 室内短测数据 |
| `data/track_summary.json` | 户外定位质量统计摘要 |
| `data/esp_phone_compare_summary.json` | ESP32 与手机参考轨迹对比摘要 |
| `data/indoor_outdoor_quality_summary.json` | 室内外定位质量对比摘要 |
| `data/track.html` | folium 户外轨迹地图 |
| `data/esp_phone_overlay.html` | ESP32 与手机参考轨迹叠加地图 |

原始手机轨迹文件包含个人位置隐私，不放入最终提交包；报告中使用已生成的截图、叠加地图和统计摘要作为对比证据。

## 报告图片

| 文件 | 说明 |
|---|---|
| `assets/real_wiring_photo.jpg` | ESP32 与 GNSS 模块真实接线图 |
| `assets/phone_app_track_screenshot.jpg` | 手机运动 App 同步轨迹截图 |
| `assets/esp32_outdoor_track_map.png` | ESP32 户外轨迹地图截图 |
| `assets/esp32_phone_overlay_map.png` | ESP32 与手机参考轨迹叠加截图 |
| `assets/hdop_satellite_time_series.png` | HDOP 与卫星数随时间变化 |
| `assets/satellite_count_distribution.png` | 卫星数分布 |
| `assets/esp_phone_nearest_distance.png` | ESP32 到手机参考轨迹最近距离 |
| `assets/indoor_outdoor_quality_compare.png` | 室内外定位质量对比 |
| `assets/realtime_web_replay.png` | WebSocket 实时回放页面截图 |

## 运行方式

安装依赖：

```powershell
pip install -r requirements.txt
```

运行 NMEA 解析器测试：

```powershell
python code\02_test_gnss_parser.py
```

重新生成 folium 地图和统计图：

```powershell
python code\plot_track.py --track data\track_flash_outdoor_001.csv
```

重新生成 ESP32 与手机参考轨迹对比：

```powershell
python code\compare_esp_phone.py
```

重新生成室内外定位质量统计：

```powershell
python code\compare_environment_quality.py
```

运行 Web 实时回放页面：

```powershell
python code\realtime_web_visualizer.py --mode replay --csv data\track_flash_outdoor_001.csv
```

浏览器打开：

```text
http://127.0.0.1:5000
```

## 报告编译

使用 XeLaTeX 编译：

```powershell
xelatex report_lab3_final.tex
xelatex report_lab3_final.tex
```

最终报告文件为：

```text
report_lab3_final.pdf
```
