import os
import runpy
import sys
import tempfile
from pathlib import Path

local_tmp = Path(r"F:\mechineSight\stm32\罗丹\tmp\lo_tmp")
local_tmp.mkdir(parents=True, exist_ok=True)
os.environ["TMP"] = str(local_tmp)
os.environ["TEMP"] = str(local_tmp)
os.environ["TMPDIR"] = str(local_tmp)
tempfile.tempdir = str(local_tmp)

render_script = Path(r"C:\Users\danwai\.codex\plugins\cache\openai-primary-runtime\documents\26.630.12135\skills\documents\render_docx.py")
sys.argv = [str(render_script)] + sys.argv[1:]
runpy.run_path(str(render_script), run_name="__main__")
