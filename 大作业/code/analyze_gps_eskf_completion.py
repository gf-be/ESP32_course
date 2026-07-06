from pathlib import Path
import runpy


SCRIPT = (
    Path(__file__).resolve().parent
    / "sensor-final-project"
    / "firmware"
    / "fusion"
    / "analyze_gps_eskf_completion.py"
)

runpy.run_path(str(SCRIPT), run_name="__main__")
