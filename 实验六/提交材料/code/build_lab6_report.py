"""Rebuild Lab 6 figures and compile the LaTeX report."""

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def run(cmd):
    print("+", " ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def main():
    run([sys.executable, str(ROOT / "code" / "analyze_bmp280_staircase.py")])
    run([sys.executable, str(ROOT / "code" / "analyze_gps_baro_fusion.py")])
    run(["xelatex", "-interaction=nonstopmode", "-halt-on-error", "report_lab6_final.tex"])
    run(["xelatex", "-interaction=nonstopmode", "-halt-on-error", "report_lab6_final.tex"])
    for suffix in [".aux", ".log", ".out", ".toc"]:
        p = ROOT / ("report_lab6_final" + suffix)
        if p.exists():
            try:
                p.unlink()
            except PermissionError:
                print("Warning: could not remove", p)


if __name__ == "__main__":
    main()
