# 提交目录核对清单

生成时间：2026-07-05 16:39:54

## 目录状态

| 模块 | 路径 | 状态 | 说明 |
|---|---|---|---|
| 硬件设计 | `hardware/` | 已整理 | 含原理图、PCB PDF、Gerber、BOM 和实物照片 |
| 固件代码 | `firmware/` | 已整理 | 含 drivers、calibration、fusion、ai_enhance、performance、tools 和 main.py |
| 原始/分析数据 | `data/` | 已整理 | 含 calibration、fusion_comparison、performance、analysis、figures 等 |
| 文档 | `docs/` | 已整理 | 含 spec.md、test_report.md、演示说明、系统架构图和报告草稿 |
| 演示视频 | `demo.mp4` | 不提交 | 已向老师确认可以不需要 |
| 最终报告 PDF | `docs/final_report.pdf` | 待手动加入 | 最终 Word/PDF 由作者排版后放入 |

## 硬件文件

- `hardware/schematic.pdf`：原理图 PDF。
- `hardware/pcb.pdf`：PCB 版图/正反面/订单图合成 PDF。
- `hardware/gerber/`：Gerber 生产文件目录。
- `hardware/BOM.csv`：合并后的物料清单。
- `hardware/BOM_merged.xlsx`：便于人工查看的 Excel 版 BOM。

## 关键数据与图片

- 标定原始数据：`data/calibration/`。
- 姿态融合与 ESKF 数据：`data/fusion_comparison/`。
- 性能测试数据：`data/performance/`。
- 分析结果表：`data/analysis/` 与 `data/*.csv`。
- 报告图片：`data/figures/` 与 `docs/photos/`。

## 文件数量统计

- hardware 文件数：28
- firmware 文件数：67
- data 文件数：188
- docs 文件数：231

## 提交前最后一步

1. 将最终排版后的课程论文 PDF 放入 `docs/final_report.pdf`。
2. 确认 `README.md`、`docs/spec.md`、`docs/test_report.md` 可以正常打开。
3. 若老师要求压缩包提交，直接压缩整个 `sensor-final-project/` 文件夹。
