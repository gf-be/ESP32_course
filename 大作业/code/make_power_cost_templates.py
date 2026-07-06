# -*- coding: utf-8 -*-
"""
Create power and cost templates for the final report.

Fill measured current and real purchase prices in the generated CSV files.
"""

from pathlib import Path
import csv


ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "data" / "performance"


POWER_ROWS = [
    ["idle", "ESP32上电、传感器初始化后空闲", "", "mA", "3.3", "V", "", "万用表串联供电正极，记录稳定读数"],
    ["sampling", "IMU+磁力计连续采集并串口输出", "", "mA", "3.3", "V", "", "运行采集脚本时记录稳定读数"],
    ["fusion", "姿态融合算法运行", "", "mA", "3.3", "V", "", "运行频率/融合测试脚本时记录稳定读数"],
]


COST_ROWS = [
    ["PCB打样", 1, "", "元", "", "按实际订单均摊"],
    ["MPU6050/兼容IMU模块或芯片", 1, "", "元", "", "0x68 IMU"],
    ["HMC5883L/GY-273磁力计", 1, "", "元", "", "0x1E 磁力计"],
    ["BMP280气压计", 1, "", "元", "", "0x76 气压计"],
    ["阻容器件", 1, "", "元", "", "电阻、电容合计"],
    ["排针/连接器", 1, "", "元", "", "排针、杜邦线或连接座"],
    ["LED", 1, "", "元", "", "指示灯"],
    ["其他焊接/辅料", 1, "", "元", "", "锡丝、助焊剂等可选"],
]


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    power_path = OUT_DIR / "power_measurement_template.csv"
    with power_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["state", "description", "current_mA", "current_unit", "voltage", "voltage_unit", "power_mW", "note"])
        writer.writerows(POWER_ROWS)

    cost_path = OUT_DIR / "cost_bom_template.csv"
    with cost_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["item", "quantity", "unit_price", "currency", "subtotal", "note"])
        writer.writerows(COST_ROWS)

    print("Wrote:", power_path)
    print("Wrote:", cost_path)
    print("Fill current_mA and unit_price/subtotal, then send the files back for report summary.")


if __name__ == "__main__":
    main()
