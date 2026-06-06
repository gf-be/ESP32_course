# 实验三 GitHub 提交内容

本清单对应当前最终提交包，仅列出需要提交且实际存在的文件。

## 一、报告文件

| 文件 | 说明 |
|---|---|
| `report_lab3_final.pdf` | 最终 PDF 报告 |
| `report_lab3_final.tex` | LaTeX 报告源码 |
| `README.md` | 项目说明与运行方式 |
| `requirements.txt` | Python 依赖 |

## 二、代码文件

| 文件 | 对应内容 |
|---|---|
| `code/gnss_nmea.py` | 自写 NMEA 解析器 |
| `code/01_gnss_nmea_smoke.py` | 串口接收与原始 NMEA 验证 |
| `code/02_test_gnss_parser.py` | NMEA 解析器单元测试 |
| `code/03_wifi_udp_track.py` | ESP32 WiFi UDP 上传 |
| `code/04_serial_track_logger.py` | 串口记录备用脚本 |
| `code/05_flash_track_logger.py` | ESP32 Flash 离线采集 |
| `code/receiver.py` | 电脑端 UDP 接收并保存 CSV |
| `code/plot_track.py` | folium 地图与定位质量统计图 |
| `code/compare_esp_phone.py` | ESP32 与手机参考轨迹对比 |
| `code/compare_environment_quality.py` | 室内外定位质量统计 |
| `code/realtime_web_visualizer.py` | Flask + WebSocket + Leaflet 实时回放 |
| `code/config_wifi.py.example` | WiFi 配置模板，不含真实密码 |

## 三、实测数据与分析结果

| 文件 | 说明 |
|---|---|
| `data/track_flash_outdoor_001.csv` | 户外主实验数据，1051 点 |
| `data/track_20260605_212206.csv` | WiFi UDP 室内短测数据 |
| `data/track_summary.json` | 户外定位质量统计摘要 |
| `data/esp_phone_compare_summary.json` | ESP32 与手机参考轨迹对比摘要 |
| `data/indoor_outdoor_quality_summary.json` | 室内外定位质量对比摘要 |
| `data/track.html` | folium 户外轨迹地图 |
| `data/esp_phone_overlay.html` | ESP32 与手机参考轨迹叠加地图 |

原始手机轨迹文件包含个人位置隐私，不放入最终提交包；报告中保留处理后的地图、截图和统计摘要。

## 四、报告图片

| 文件 | 说明 |
|---|---|
| `assets/real_wiring_photo.jpg` | ESP32 与 GNSS 模块真实接线图 |
| `assets/phone_app_track_screenshot.jpg` | 手机运动 App 同步轨迹截图 |
| `assets/esp32_outdoor_track_map.png` | 户外实测轨迹地图截图 |
| `assets/esp32_phone_overlay_map.png` | ESP32 与手机参考轨迹叠加截图 |
| `assets/hdop_satellite_time_series.png` | HDOP 与卫星数随时间变化 |
| `assets/satellite_count_distribution.png` | 卫星数分布 |
| `assets/esp_phone_nearest_distance.png` | ESP32 到手机参考轨迹最近距离统计 |
| `assets/indoor_outdoor_quality_compare.png` | 室内外定位质量统计图 |
| `assets/realtime_web_replay.png` | WebSocket 实时回放可视化截图 |

## 五、完成度证据

| 项目 | 当前证据 |
|---|---|
| 解析器实现 | `code/gnss_nmea.py`，单元测试 6/6 PASS |
| WiFi 上传 | `code/03_wifi_udp_track.py`，`data/track_20260605_212206.csv` |
| 户外采集 | `data/track_flash_outdoor_001.csv`，1051 点，有效率 82.11% |
| folium 可视化 | `data/track.html` 与 `assets/esp32_outdoor_track_map.png` |
| 定位质量统计 | `assets/hdop_satellite_time_series.png`、`assets/satellite_count_distribution.png` |
| 手机参考轨迹对比 | `data/esp_phone_overlay.html`、`assets/esp32_phone_overlay_map.png` |
| Web 实时可视化 | `code/realtime_web_visualizer.py`、`assets/realtime_web_replay.png` |
| 室内外定位质量统计 | `code/compare_environment_quality.py`、`assets/indoor_outdoor_quality_compare.png` |
| AI 协作记录 | 已写入 `report_lab3_final.pdf` |

## 六、建议提交方式

建议直接提交 `final_submission` 目录中的内容。
