"""
Install the ESP32 GPS offline logger as /main.py.

Run this file on the computer with local Python. Close Thonny's Shell first if
COM4 is busy. After installation, the ESP32 will automatically start GPS
logging on power-up/reset and save logs under /gps_logs.
"""

from pathlib import Path
import serial
import time


COM_PORT = "COM4"
BAUDRATE = 115200
SOURCE_FILE = Path(__file__).resolve().parents[1] / "drivers" / "esp32_gps_offline_logger_main.py"
TARGET_FILE = "main.py"


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
    print("Installing ESP32 GPS offline logger")
    print("Port:", COM_PORT)
    print("Source:", SOURCE_FILE)
    print("Target on ESP32: /%s" % TARGET_FILE)

    with serial.Serial(COM_PORT, BAUDRATE, timeout=1) as ser:
        enter_raw_repl(ser)
        before = exec_raw(
            ser,
            "import os\nprint('before_files:', os.listdir())\n",
            timeout=10,
            read_output=True,
        )
        print(before.strip())

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

    print("Done. Reset/power-on will run /main.py automatically.")
    print("GPS logs will be saved on ESP32 under /gps_logs.")


if __name__ == "__main__":
    main()
