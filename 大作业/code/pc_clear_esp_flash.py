"""
Run this file on the computer with Thonny's local Python interpreter.

It connects to the ESP32 MicroPython REPL and removes user files from the
ESP32 internal flash. It does not upload this script to the ESP32.
"""

import serial
import time


COM_PORT = "COM7"  # Change this to your ESP32 port, for example COM3/COM5/COM8.
BAUDRATE = 115200

# Keep boot.py by default so MicroPython can still start normally.
KEEP_NAMES = {"boot.py"}


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
    time.sleep(0.2)
    ser.reset_input_buffer()
    ser.write(b"\x01")
    read_until(ser, b">", timeout=5)


def exit_raw_repl(ser):
    ser.write(b"\x02")
    time.sleep(0.2)


def run_remote_code(ser, code):
    enter_raw_repl(ser)
    data = code.encode("utf-8")
    for i in range(0, len(data), 128):
        ser.write(data[i : i + 128])
        time.sleep(0.01)
    ser.write(b"\x04")
    read_until(ser, b"OK", timeout=5)
    output = read_until(ser, b"\x04", timeout=20).replace(b"\x04", b"")
    error = read_until(ser, b"\x04", timeout=5).replace(b"\x04", b"")
    exit_raw_repl(ser)
    if error.strip():
        raise RuntimeError(error.decode("utf-8", errors="replace"))
    return output.decode("utf-8", errors="replace")


REMOTE_CLEAN_CODE = r'''
import os

KEEP_NAMES = __KEEP_NAMES__

def remove_path(path):
    try:
        names = os.listdir(path)
        is_dir = True
    except OSError:
        names = None
        is_dir = False

    if is_dir:
        for name in names:
            child = path + "/" + name if path != "/" else "/" + name
            if child.lstrip("/") in KEEP_NAMES:
                print("keep", child)
            else:
                remove_path(child)
        if path != "/":
            try:
                os.rmdir(path)
                print("removed dir", path)
            except OSError as exc:
                print("skip dir", path, exc)
    else:
        try:
            os.remove(path)
            print("removed file", path)
        except OSError as exc:
            print("skip file", path, exc)

print("before:", os.listdir())
for name in os.listdir():
    if name in KEEP_NAMES:
        print("keep", name)
    else:
        remove_path("/" + name)
print("after:", os.listdir())
'''


def main():
    keep_repr = repr(sorted(KEEP_NAMES))
    code = REMOTE_CLEAN_CODE.replace("__KEEP_NAMES__", keep_repr)
    print("Connecting to", COM_PORT)
    with serial.Serial(COM_PORT, BAUDRATE, timeout=0.2) as ser:
        output = run_remote_code(ser, code)
    print(output)
    print("ESP32 flash cleanup finished.")


if __name__ == "__main__":
    main()
