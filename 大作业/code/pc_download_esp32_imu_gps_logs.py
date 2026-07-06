from pathlib import Path
import runpy


SCRIPT = (
    Path(__file__).resolve().parent
    / "sensor-final-project"
    / "firmware"
    / "tools"
    / "pc_download_esp32_imu_gps_logs.py"
)

runpy.run_path(str(SCRIPT), run_name="__main__")
