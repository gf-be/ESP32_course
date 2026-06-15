# 提交说明

本目录为实验二提交包。

- 姓名：罗丹
- 学号：2251801014
- 实验名称：实验二 MCU 基础原理

建议提交整个 `experiment2_submission_20260529` 文件夹，至少包含：

- `report.md`
- `index.html`
- `data/`
- `assets/`
- `code/`

边界说明：

- GPIO、PWM、ADC、定时器中断、GPIO 中断、DMA 双缓冲、时间戳均基于 ESP32-S3 板内外设完成。
- ADC/PWM 使用 `GPIO5 -> GPIO4` 板内回环；ESP-IDF 中断优先级补测使用 `GPIO7 -> GPIO6`。
- 标准 MicroPython 固件没有 ADC DMA 接口，因此 DMA 双缓冲与不同中断优先级选做项使用 `code/espidf_dma_irq/` 中的 ESP-IDF 工程补测。
