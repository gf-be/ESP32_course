# -*- coding: utf-8 -*-
"""Convenience launcher for synchronized IMU + GPS ESKF capture."""

from pathlib import Path
import runpy


SCRIPT = (
    Path(__file__).resolve().parent
    / "sensor-final-project"
    / "firmware"
    / "fusion"
    / "pc_imu_gps_sync_capture.py"
)

runpy.run_path(str(SCRIPT), run_name="__main__")
