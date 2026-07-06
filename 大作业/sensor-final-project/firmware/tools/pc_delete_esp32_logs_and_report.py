"""
Delete ESP32 log directories and print flash free space.

This keeps program files such as boot.py, main.py, gps_baro_fusion.py, and
main_gps_autorun_backup.py. It only removes data/log folders.
"""

import serial
import time


COM_PORT = "COM4"
BAUDRATE = 115200
LOG_DIRS = ["/gps_logs", "/gps_baro_logs", "/bmp280_stair"]


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


def run_remote_code(ser, code, timeout=60):
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
LOG_DIRS = __LOG_DIRS__

def is_dir(path):
    try:
        os.listdir(path)
        return True
    except OSError:
        return False

def remove_path(path):
    if is_dir(path):
        for name in os.listdir(path):
            child = path + "/" + name if path != "/" else "/" + name
            remove_path(child)
        try:
            os.rmdir(path)
            print("removed_dir,%s" % path)
        except OSError as exc:
            print("skip_dir,%s,%r" % (path, exc))
    else:
        try:
            os.remove(path)
            print("removed_file,%s" % path)
        except OSError as exc:
            print("skip_file,%s,%r" % (path, exc))

print("before_files,%r" % (os.listdir(),))
for path in LOG_DIRS:
    remove_path(path)
try:
    st = os.statvfs("/")
    block_size = st[0]
    total = st[2] * block_size
    free = st[3] * block_size
    print("FLASH,total,%d,free,%d" % (total, free))
except Exception as exc:
    print("FLASH,error,%r" % (exc,))
print("after_files,%r" % (os.listdir(),))
for name in os.listdir():
    try:
        print("STAT,/%s,%d" % (name, os.stat(name)[6]))
    except Exception as exc:
        print("STAT,/%s,error,%r" % (name, exc))
'''


def main():
    print("Delete ESP32 log directories")
    print("Port:", COM_PORT)
    print("Deleting:", ", ".join(LOG_DIRS))
    code = REMOTE_CODE.replace("__LOG_DIRS__", repr(LOG_DIRS))
    with serial.Serial(COM_PORT, BAUDRATE, timeout=1) as ser:
        print(run_remote_code(ser, code))


if __name__ == "__main__":
    main()
