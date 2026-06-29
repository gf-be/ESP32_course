"""
Install ESP32 Mahony PI real-time attitude program as /main.py.

Run this file on the computer with Thonny's local Python interpreter.
Close any active ESP32 REPL/Shell connection first if the COM port is busy.
"""

from pathlib import Path
import serial
import time


COM_PORT = "COM7"
BAUDRATE = 115200
SOURCE_FILE = Path(__file__).resolve().parent / "esp32_mahony_pi_main.py"
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
    time.sleep(0.3)
    ser.reset_input_buffer()
    ser.write(b"\x01")
    read_until(ser, b">", timeout=5)


def exec_raw(ser, code, timeout=10):
    data = code.encode("utf-8")
    for i in range(0, len(data), 128):
        ser.write(data[i:i + 128])
        time.sleep(0.005)
    ser.write(b"\x04")
    read_until(ser, b"OK", timeout=timeout)
    time.sleep(0.05)


def soft_reset(ser):
    ser.write(b"\x02")
    time.sleep(0.2)
    ser.write(b"\x04")
    time.sleep(1.0)


def main():
    source = SOURCE_FILE.read_text(encoding="utf-8")
    print("Installing:", SOURCE_FILE)
    print("Target on ESP32:", TARGET_FILE)
    print("Port:", COM_PORT)

    with serial.Serial(COM_PORT, BAUDRATE, timeout=1) as ser:
        enter_raw_repl(ser)
        exec_raw(ser, "f=open(%r,'w')\n" % TARGET_FILE)
        for i in range(0, len(source), 512):
            chunk = source[i:i + 512]
            exec_raw(ser, "f.write(%r)\n" % chunk)
            print("written %d/%d bytes" % (min(i + 512, len(source)), len(source)))
        exec_raw(ser, "f.close()\n")
        exec_raw(ser, "import os\nprint(os.listdir())\n")
        soft_reset(ser)

    print("Done. ESP32 will run /main.py automatically after reset.")


if __name__ == "__main__":
    main()
