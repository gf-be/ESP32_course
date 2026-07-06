"""
Convenience launcher for the submitted-project accelerometer 12-parameter
calibration script.
"""

from pathlib import Path
import runpy


SCRIPT = (
    Path(__file__).resolve().parent
    / "sensor-final-project"
    / "firmware"
    / "calibration"
    / "analyze_accel_6pos_12param.py"
)

runpy.run_path(str(SCRIPT), run_name="__main__")
