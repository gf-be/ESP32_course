from pathlib import Path
import runpy


SCRIPT = (
    Path(__file__).resolve().parent
    / "sensor-final-project"
    / "firmware"
    / "tools"
    / "pc_install_esp32_imu_gps_logger.py"
)

runpy.run_path(str(SCRIPT), run_name="__main__")
