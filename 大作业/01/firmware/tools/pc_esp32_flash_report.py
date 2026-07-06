"""
Print ESP32 MicroPython flash usage and recursive file sizes.
"""

import serial
import time


COM_PORT = "COM4"
BAUDRATE = 115200


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


def exit_raw_repl(ser):
    ser.write(b"\x02")
    time.sleep(0.2)


def run_remote_code(ser, code, timeout=20):
    enter_raw_repl(ser)
    data = code.encode("utf-8")
    for i in range(0, len(data), 128):
        ser.write(data[i:i + 128])
        time.sleep(0.005)
    ser.write(b"\x04")
    read_until(ser, b"OK", timeout=timeout)
    out = read_until(ser, b"\x04", timeout=timeout).replace(b"\x04", b"")
    err = read_until(ser, b"\x04", timeout=timeout).replace(b"\x04", b"")
    exit_raw_repl(ser)
    if err.strip():
        raise RuntimeError(err.decode("utf-8", errors="replace"))
    return out.decode("utf-8", errors="replace")


REMOTE_CODE = r'''
import os

def is_dir(path):
    try:
        os.listdir(path)
        return True
    except OSError:
        return False

def size_of(path):
    try:
        return os.stat(path)[6]
    except OSError:
        return -1

def walk(path):
    try:
        names = os.listdir(path)
    except OSError:
        print("FILE,%s,%d" % (path, size_of(path)))
        return
    total = 0
    for name in names:
        child = path + "/" + name if path != "/" else "/" + name
        if is_dir(child):
            before = total
            walk(child)
        else:
            sz = size_of(child)
            print("FILE,%s,%d" % (child, sz))
            total += max(sz, 0)
    print("DIR,%s,%d" % (path, total))

try:
    st = os.statvfs("/")
    block_size = st[0]
    total = st[2] * block_size
    free = st[3] * block_size
    print("FLASH,total,%d,free,%d" % (total, free))
except Exception as exc:
    print("FLASH,error,%r" % (exc,))

walk("/")
'''


def main():
    print("ESP32 flash report")
    print("Port:", COM_PORT)
    with serial.Serial(COM_PORT, BAUDRATE, timeout=1) as ser:
        print(run_remote_code(ser, REMOTE_CODE))


if __name__ == "__main__":
    main()
