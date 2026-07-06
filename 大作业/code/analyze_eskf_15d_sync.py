# -*- coding: utf-8 -*-
"""Convenience launcher for synchronized IMU+GPS 15D ESKF analysis."""

from pathlib import Path
import runpy


SCRIPT = (
    Path(__file__).resolve().parent
    / "sensor-final-project"
    / "firmware"
    / "fusion"
    / "analyze_eskf_15d_sync.py"
)

runpy.run_path(str(SCRIPT), run_name="__main__")
