# GPS 户外轨迹与手机 GNSS 参考轨迹对比分析

## 对应课程要求

评分标准中“数据可视化（必做）”明确要求完成“GPS 轨迹叠加，Python folium，户外测试轨迹”。本次新增 `20260629户外步行.gpx` 作为手机 GNSS 参考轨迹，并与 ESP32 + GPS6MV2/NEO-6M 离线采集轨迹进行空间叠加和误差对照，可用于补强论文第 6.4 节 GPS 轨迹对比与可视化内容。

## 数据来源

手机参考轨迹：`F:\mechineSight\stm32\罗丹\大作业\data\20260629户外步行.gpx`

ESP32 轨迹：`F:\mechineSight\stm32\罗丹\大作业\sensor-final-project\data\analysis\gps_track_points_offline_20260629_215118.csv`

手机 GPX 中包含 404 个轨迹点，扩展字段记录总时间为 940 s，总距离为 951 m。ESP32 离线采集得到 1456 个有效 GPS 点，其中按 `satellites >= 4` 且 `HDOP <= 5` 筛选后保留 1364 个质量较好的点。

## 主要结果

| 指标 | 手机 GNSS 参考轨迹 | ESP32 原始轨迹 | ESP32 质量筛选轨迹 |
|---|---:|---:|---:|
| 轨迹点数 | 404 | 1456 | 1364 |
| 轨迹距离 | 951.0 m | 1750.3 m | 1641.1 m |
| 到手机轨迹最近距离中位数 | - | 2.71 m | 2.56 m |
| 到手机轨迹最近距离 95% 分位 | - | 21.21 m | 18.27 m |
| 质量筛选条件 | - | 无 | 卫星数 >= 4 且 HDOP <= 5 |

ESP32 的总轨迹距离明显大于手机 GPX，主要原因是 ESP32 离线记录持续时间更长，包含了手机运动记录未覆盖的附加路段。因此，本实验不直接用总距离差作为定位精度评价，而采用轨迹空间最近邻距离评价两条轨迹在重叠路段上的一致性。

结果显示，ESP32 原始轨迹到手机参考轨迹的最近距离中位数为 2.71 m，质量筛选后进一步降至 2.56 m；95% 分位误差由 21.21 m 降至 18.27 m。考虑到低成本 GPS6MV2/NEO-6M 模块、城市/校园环境遮挡、多路径反射和手机 GNSS 本身也非严格真值，该结果说明 ESP32 GPS 模块能够形成可用的户外步行轨迹，满足课程中 GPS 轨迹叠加可视化要求，并可作为后续 GPS/IMU 融合实验的数据来源。

## 图题建议

图 X  ESP32 离线 GPS 轨迹与手机 GNSS 参考轨迹叠加图

图 X  ESP32 GPS 轨迹点到手机 GNSS 参考轨迹的最近距离分布

图 X  基于 folium 的 ESP32 与手机 GNSS 户外轨迹网页叠加显示

表 X  ESP32 GPS 与手机 GNSS 参考轨迹对比统计结果

## 已生成文件

轨迹叠加图：`F:\mechineSight\stm32\罗丹\大作业\sensor-final-project\data\figures\gps_esp32_phone_overlay_20260629.png`

误差分布图：`F:\mechineSight\stm32\罗丹\大作业\sensor-final-project\data\figures\gps_esp32_phone_error_hist_20260629.png`

folium 网页地图：`F:\mechineSight\stm32\罗丹\大作业\sensor-final-project\data\figures\gps_esp32_phone_overlay_20260629.html`

对比统计表：`F:\mechineSight\stm32\罗丹\大作业\sensor-final-project\data\analysis\gps_esp32_vs_phone_summary_20260629.csv`
