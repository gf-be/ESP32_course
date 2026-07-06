from __future__ import annotations

import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from PIL import Image


PROJECT = Path(__file__).resolve().parents[2]
HARDWARE = PROJECT / "hardware"
DOCS = PROJECT / "docs"
DATA = PROJECT / "data"
FIRMWARE = PROJECT / "firmware"


def copy_if_needed(src: Path, dst: Path) -> None:
    if not src.exists():
        raise FileNotFoundError(src)
    if dst.exists() and dst.read_bytes() == src.read_bytes():
        return
    shutil.copy2(src, dst)


def image_to_pdf(images: list[Path], out_pdf: Path) -> None:
    pages = []
    for path in images:
        if not path.exists():
            continue
        img = Image.open(path).convert("RGB")
        max_w, max_h = 1600, 2200
        img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (max_w, max_h), "white")
        x = (max_w - img.width) // 2
        y = (max_h - img.height) // 2
        canvas.paste(img, (x, y))
        pages.append(canvas)
    if not pages:
        raise FileNotFoundError("No PCB images found for pcb.pdf")
    pages[0].save(out_pdf, save_all=True, append_images=pages[1:])


def extract_gerber() -> None:
    gerber_zip = HARDWARE / "gerber.zip"
    gerber_dir = HARDWARE / "gerber"
    gerber_dir.mkdir(parents=True, exist_ok=True)
    if not gerber_zip.exists():
        return
    with zipfile.ZipFile(gerber_zip, "r") as zf:
        for member in zf.infolist():
            if member.is_dir():
                continue
            target = gerber_dir / member.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.stat().st_size == member.file_size:
                continue
            with zf.open(member) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)


def count_files(folder: Path) -> int:
    return sum(1 for p in folder.rglob("*") if p.is_file()) if folder.exists() else 0


def write_submission_index() -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 提交目录核对清单",
        "",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 目录状态",
        "",
        "| 模块 | 路径 | 状态 | 说明 |",
        "|---|---|---|---|",
        "| 硬件设计 | `hardware/` | 已整理 | 含原理图、PCB PDF、Gerber、BOM 和实物照片 |",
        "| 固件代码 | `firmware/` | 已整理 | 含 drivers、calibration、fusion、ai_enhance、performance、tools 和 main.py |",
        "| 原始/分析数据 | `data/` | 已整理 | 含 calibration、fusion_comparison、performance、analysis、figures 等 |",
        "| 文档 | `docs/` | 已整理 | 含 spec.md、test_report.md、演示说明、系统架构图和报告草稿 |",
        "| 演示视频 | `demo.mp4` | 不提交 | 已向老师确认可以不需要 |",
        "| 最终报告 PDF | `docs/final_report.pdf` | 待手动加入 | 最终 Word/PDF 由作者排版后放入 |",
        "",
        "## 硬件文件",
        "",
        "- `hardware/schematic.pdf`：原理图 PDF。",
        "- `hardware/pcb.pdf`：PCB 版图/正反面/订单图合成 PDF。",
        "- `hardware/gerber/`：Gerber 生产文件目录。",
        "- `hardware/BOM.csv`：合并后的物料清单。",
        "- `hardware/BOM_merged.xlsx`：便于人工查看的 Excel 版 BOM。",
        "",
        "## 关键数据与图片",
        "",
        "- 标定原始数据：`data/calibration/`。",
        "- 姿态融合与 ESKF 数据：`data/fusion_comparison/`。",
        "- 性能测试数据：`data/performance/`。",
        "- 分析结果表：`data/analysis/` 与 `data/*.csv`。",
        "- 报告图片：`data/figures/` 与 `docs/photos/`。",
        "",
        "## 文件数量统计",
        "",
        f"- hardware 文件数：{count_files(PROJECT / 'hardware')}",
        f"- firmware 文件数：{count_files(PROJECT / 'firmware')}",
        f"- data 文件数：{count_files(PROJECT / 'data')}",
        f"- docs 文件数：{count_files(PROJECT / 'docs')}",
        "",
        "## 提交前最后一步",
        "",
        "1. 将最终排版后的课程论文 PDF 放入 `docs/final_report.pdf`。",
        "2. 确认 `README.md`、`docs/spec.md`、`docs/test_report.md` 可以正常打开。",
        "3. 若老师要求压缩包提交，直接压缩整个 `sensor-final-project/` 文件夹。",
    ]
    (DOCS / "submission_index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    copy_if_needed(HARDWARE / "SCH原理图.pdf", HARDWARE / "schematic.pdf")
    image_to_pdf(
        [
            HARDWARE / "PCB正面图.jpg",
            HARDWARE / "PCB反面图.jpg",
            HARDWARE / "PCB订单图.png",
            HARDWARE / "PCB连接完模块图.jpg",
            HARDWARE / "焊接结果图.jpg",
        ],
        HARDWARE / "pcb.pdf",
    )
    extract_gerber()
    write_submission_index()
    print("submission package prepared")
    print(PROJECT)


if __name__ == "__main__":
    main()
