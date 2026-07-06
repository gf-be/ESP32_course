# -*- coding: utf-8 -*-
"""Convenience launcher for the submitted-project Madgwick fusion analysis."""

from pathlib import Path
import runpy


SCRIPT = (
    Path(__file__).resolve().parent
    / "sensor-final-project"
    / "firmware"
    / "fusion"
    / "analyze_attitude_fusion_madgwick.py"
)

runpy.run_path(str(SCRIPT), run_name="__main__")
