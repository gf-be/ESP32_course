# 15 维简化 ESKF 离线实验分析

## 实验定位

本实验实现课程论文要求中的误差状态卡尔曼滤波（ESKF）部分。由于当前户外步行数据尚未包含严格同步的 IMU+GPS 原始序列，本版本采用“离线 15 维简化 ESKF”形式：保持完整 15 维误差状态和名义状态结构，使用 ESP32 GPS 离线轨迹作为位置观测，采用零加速度/常速度模型作为预测项。该实验适合用于论文中说明 ESKF 状态设计、预测-更新流程和 GPS 轨迹平滑效果；后续采集同步 IMU+GPS 日志后，只需替换预测输入即可接入真实惯导预测。

误差状态定义为：

```text
delta x = [delta p, delta v, delta theta, delta bg, delta ba]^T
```

其中 `delta p` 为 3 维位置误差，`delta v` 为 3 维速度误差，`delta theta` 为 3 维姿态误差，`delta bg` 为 3 维陀螺仪零偏误差，`delta ba` 为 3 维加速度计零偏误差，总维度为 15。

名义状态定义为：

```text
x = [p, v, q, bg, ba]
```

其中 `p` 为位置，`v` 为速度，`q` 为姿态四元数，`bg` 和 `ba` 分别为陀螺仪与加速度计零偏。

## 数据来源

ESP32 GPS 数据：`F:\mechineSight\stm32\罗丹\大作业\sensor-final-project\data\analysis\gps_track_points_offline_20260629_215118.csv`

手机 GNSS 参考轨迹：`F:\mechineSight\stm32\罗丹\大作业\sensor-final-project\data\analysis\gps_phone_reference_points_20260629.csv`

GPS 质量筛选条件为：

```text
satellites >= 4 且 HDOP <= 5
```

筛选后保留 1364 个 GPS 点，ESKF 对应输出 1364 个状态估计点，GPS 更新接受 1364 次，拒绝 0 次。

## 主要结果

| 指标 | GPS 质量筛选轨迹 | 15 维简化 ESKF |
|---|---:|---:|
| 轨迹点数 | 1364 | 1364 |
| 轨迹距离 | 1641.05 m | 1456.75 m |
| 到手机参考轨迹最近距离均值 | 7.18 m | 7.28 m |
| 到手机参考轨迹最近距离中位数 | 2.56 m | 2.59 m |
| 到手机参考轨迹最近距离 95% 分位 | 18.27 m | 16.79 m |
| 30 m 匹配路段 95% 分位 | 12.62 m | 12.34 m |

结果表明，在未接入同步 IMU 的条件下，ESKF 对轨迹尖峰和局部跳变具有一定平滑作用，轨迹总长度由 1641.05 m 降至 1456.75 m，说明轨迹抖动被抑制；相对于手机 GNSS 参考轨迹，95% 分位最近距离由 18.27 m 降至 16.79 m，30 m 匹配路段的 95% 分位由 12.62 m 降至 12.34 m。中位误差基本保持在约 2.6 m，说明 ESKF 没有显著改变大部分正常 GPS 点的位置，而主要改善局部大误差和轨迹平滑性。

需要说明的是，本实验当前为 GPS-only fallback 模式，预测项没有使用同步 IMU 高频加速度和角速度，因此不应将其描述为完整 GPS/IMU 紧耦合融合。论文中建议表述为“15 维 ESKF 离线框架验证与 GPS 轨迹平滑实验”。若后续补采同步 IMU+GPS 数据，可进一步将 IMU 高频预测与 GPS 低频修正结合，实现更完整的 GPS/IMU 多速率 ESKF。

## 图题建议

图 X  离线 15 维简化 ESKF 轨迹与 GPS/手机参考轨迹对比

图 X  GPS 质量筛选轨迹与 15 维简化 ESKF 轨迹最近距离误差对比

图 X  15 维简化 ESKF 的 GPS 创新量与位置协方差变化曲线

图 X  基于 folium 的 GPS 质量筛选轨迹、ESKF 轨迹与手机参考轨迹网页叠加显示

表 X  离线 15 维简化 ESKF 与 GPS 质量筛选轨迹误差统计表

## 已生成文件

分析脚本：`F:\mechineSight\stm32\罗丹\大作业\sensor-final-project\firmware\fusion\analyze_eskf_15d_offline.py`

状态输出：`F:\mechineSight\stm32\罗丹\大作业\sensor-final-project\data\analysis\eskf_15d_offline_states_20260629.csv`

统计表：`F:\mechineSight\stm32\罗丹\大作业\sensor-final-project\data\analysis\eskf_15d_offline_summary_20260629.csv`

轨迹对比图：`F:\mechineSight\stm32\罗丹\大作业\sensor-final-project\data\figures\eskf_15d_track_overlay_20260629.png`

误差对比图：`F:\mechineSight\stm32\罗丹\大作业\sensor-final-project\data\figures\eskf_15d_error_compare_20260629.png`

创新量与协方差图：`F:\mechineSight\stm32\罗丹\大作业\sensor-final-project\data\figures\eskf_15d_innovation_20260629.png`

folium 网页地图：`F:\mechineSight\stm32\罗丹\大作业\sensor-final-project\data\figures\eskf_15d_track_overlay_20260629.html`
