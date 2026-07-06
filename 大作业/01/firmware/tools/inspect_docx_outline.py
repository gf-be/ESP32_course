from pathlib import Path
import sys

from docx import Document


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: inspect_docx_outline.py report.docx")
    path = Path(sys.argv[1])
    doc = Document(str(path))
    keywords = [
        "性能", "GPS", "ESKF", "姿态融合", "AI", "数据可视化", "实时",
        "结论", "附录", "参考", "功耗", "成本", "实验",
    ]
    for i, par in enumerate(doc.paragraphs):
        text = par.text.strip()
        if not text:
            continue
        style = par.style.name if par.style else ""
        if style.startswith("Heading") or any(k in text for k in keywords):
            safe = text[:180].encode("unicode_escape").decode("ascii")
            print(f"{i:04d}\t{style}\t{safe}")


if __name__ == "__main__":
    main()
