"""
Install ESP32 real-time 15D simplified ESKF program as /main.py.

Run this on the computer with local Python. Close Thonny Shell first if COM4 is
busy. After installation, ESP32 will run the real-time ESKF automatically after
reset or power-on.
"""

from pathlib import Path
import serial
import time


COM_PORT = "COM4"
BAUDRATE = 115200
SOURCE_FILE = Path(__file__).resolve().parents[1] / "fusion" / "esp32_eskf_15d_realtime_main.py"
TARGET_FILE = "main.py"
BACKUP_FILE = "main_before_eskf.py"


def read_until(ser, marker, timeout=5):
    end = time.time() + timeout
    data = b""
    while time.time() < end:
        chunk = ser.read(1)
        if chunk:
            data += chunk
            if marker in data:
                return data
    raise TimeoutError("Timeout waiting for %r. Received: %r" % (marker, data[-200:]))


def enter_raw_repl(ser):
    ser.write(b"\x03\x03")
    time.sleep(0.4)
    ser.reset_input_buffer()
    ser.write(b"\x01")
    read_until(ser, b">", timeout=5)


def exec_raw(ser, code, timeout=10, read_output=False):
    data = code.encode("utf-8")
    for i in range(0, len(data), 128):
        ser.write(data[i:i + 128])
        time.sleep(0.005)
    ser.write(b"\x04")
    read_until(ser, b"OK", timeout=timeout)
    out = read_until(ser, b"\x04", timeout=timeout).replace(b"\x04", b"")
    err = read_until(ser, b"\x04", timeout=timeout).replace(b"\x04", b"")
    if err.strip():
        raise RuntimeError(err.decode("utf-8", errors="replace"))
    if read_output:
        return out.decode("utf-8", errors="replace")
    return ""


def soft_reset(ser):
    ser.write(b"\x02")
    time.sleep(0.2)
    ser.write(b"\x04")
    time.sleep(1.0)


def main():
    source = SOURCE_FILE.read_text(encoding="utf-8")
    print("Installing ESP32 real-time 15D ESKF")
    print("Port:", COM_PORT)
    print("Source:", SOURCE_FILE)
    print("Target on ESP32: /%s" % TARGET_FILE)
    print("Size:", len(source), "bytes")

    with serial.Serial(COM_PORT, BAUDRATE, timeout=1) as ser:
        enter_raw_repl(ser)
        before = exec_raw(
            ser,
            "import os\nprint('before_files:', os.listdir())\n",
            timeout=10,
            read_output=True,
        )
        print(before.strip())

        backup = exec_raw(
            ser,
            "import os\n"
            "files=os.listdir()\n"
            "if %r in files and %r not in files:\n"
            "    os.rename(%r,%r)\n"
            "    print('backup_created: /%s')\n"
            "elif %r in files:\n"
            "    os.remove(%r)\n"
            "    print('existing_main_removed: backup already exists')\n"
            "else:\n"
            "    print('no_existing_main')\n"
            % (
                TARGET_FILE,
                BACKUP_FILE,
                TARGET_FILE,
                BACKUP_FILE,
                BACKUP_FILE,
                TARGET_FILE,
                TARGET_FILE,
            ),
            timeout=10,
            read_output=True,
        )
        print(backup.strip())

        exec_raw(ser, "f=open(%r,'w')\n" % TARGET_FILE)
        for i in range(0, len(source), 512):
            chunk = source[i:i + 512]
            exec_raw(ser, "f.write(%r)\n" % chunk)
            print("written %d/%d bytes" % (min(i + 512, len(source)), len(source)))
        exec_raw(ser, "f.close()\n")

        after = exec_raw(
            ser,
            "import os\nprint('after_files:', os.listdir())\n"
            "print('main_size:', os.stat('main.py')[6])\n",
            timeout=10,
            read_output=True,
        )
        print(after.strip())
        soft_reset(ser)

    print("Done. ESP32 will run /main.py automatically after reset.")


if __name__ == "__main__":
    main()
