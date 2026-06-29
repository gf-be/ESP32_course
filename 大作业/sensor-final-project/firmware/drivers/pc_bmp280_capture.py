"""
Run this file on the computer with Thonny's local Python interpreter.

It captures BMP280 pressure/temperature data through ESP32 I2C and saves CSV
files on the computer. The ESP32 only runs temporary MicroPython code in RAM.
Nothing is saved to ESP32 flash.
"""

from pathlib import Path
from datetime import datetime
import serial
import time


COM_PORT = "COM7"
BAUDRATE = 115200

SAMPLE_HZ = 5
STATIC_DURATION_S = 300
MOTION_DURATION_S = 180


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


def start_remote_code(ser, code):
    enter_raw_repl(ser)
    data = code.encode("utf-8")
    for i in range(0, len(data), 128):
        ser.write(data[i:i + 128])
        time.sleep(0.01)
    ser.write(b"\x04")
    read_until(ser, b"OK", timeout=5)


REMOTE_BMP_CODE = r'''
from machine import Pin, I2C
import time

SDA_PIN = 21
SCL_PIN = 22
I2C_FREQ = 100000
BMP_ADDR = 0x76
SAMPLE_HZ = __SAMPLE_HZ__
DURATION_S = __DURATION_S__
LABEL = "__LABEL__"

def u16le(b, i):
    return b[i] | (b[i + 1] << 8)

def s16le(b, i):
    v = u16le(b, i)
    if v & 0x8000:
        v -= 65536
    return v

class BMP280:
    def __init__(self, i2c, addr):
        self.i2c = i2c
        self.addr = addr
        calib = i2c.readfrom_mem(addr, 0x88, 24)
        self.dig_T1 = u16le(calib, 0)
        self.dig_T2 = s16le(calib, 2)
        self.dig_T3 = s16le(calib, 4)
        self.dig_P1 = u16le(calib, 6)
        self.dig_P2 = s16le(calib, 8)
        self.dig_P3 = s16le(calib, 10)
        self.dig_P4 = s16le(calib, 12)
        self.dig_P5 = s16le(calib, 14)
        self.dig_P6 = s16le(calib, 16)
        self.dig_P7 = s16le(calib, 18)
        self.dig_P8 = s16le(calib, 20)
        self.dig_P9 = s16le(calib, 22)
        self.t_fine = 0
        # ctrl_meas: temp x2, pressure x16, normal mode
        i2c.writeto_mem(addr, 0xF4, b"\x57")
        # config: standby 125ms, filter x16
        i2c.writeto_mem(addr, 0xF5, b"\x50")
        time.sleep_ms(100)

    def read_raw(self):
        d = self.i2c.readfrom_mem(self.addr, 0xF7, 6)
        adc_p = (d[0] << 12) | (d[1] << 4) | (d[2] >> 4)
        adc_t = (d[3] << 12) | (d[4] << 4) | (d[5] >> 4)
        return adc_t, adc_p

    def compensate_temp(self, adc_t):
        var1 = (((adc_t >> 3) - (self.dig_T1 << 1)) * self.dig_T2) >> 11
        var2 = (((((adc_t >> 4) - self.dig_T1) * ((adc_t >> 4) - self.dig_T1)) >> 12) * self.dig_T3) >> 14
        self.t_fine = var1 + var2
        return ((self.t_fine * 5 + 128) >> 8) / 100.0

    def compensate_pressure(self, adc_p):
        var1 = self.t_fine - 128000
        var2 = var1 * var1 * self.dig_P6
        var2 = var2 + ((var1 * self.dig_P5) << 17)
        var2 = var2 + (self.dig_P4 << 35)
        var1 = ((var1 * var1 * self.dig_P3) >> 8) + ((var1 * self.dig_P2) << 12)
        var1 = (((1 << 47) + var1) * self.dig_P1) >> 33
        if var1 == 0:
            return 0.0
        p = 1048576 - adc_p
        p = (((p << 31) - var2) * 3125) // var1
        var1 = (self.dig_P9 * (p >> 13) * (p >> 13)) >> 25
        var2 = (self.dig_P8 * p) >> 19
        p = ((p + var1 + var2) >> 8) + (self.dig_P7 << 4)
        return p / 256.0

    def read(self):
        adc_t, adc_p = self.read_raw()
        temp = self.compensate_temp(adc_t)
        pressure = self.compensate_pressure(adc_p)
        return temp, pressure

def pressure_to_altitude(p_pa, p0_pa):
    return 44330.0 * (1.0 - (p_pa / p0_pa) ** 0.1903)

i2c = I2C(0, sda=Pin(SDA_PIN), scl=Pin(SCL_PIN), freq=I2C_FREQ)
scan = i2c.scan()
if BMP_ADDR not in scan:
    print("BMP280_ERROR,no_0x76,scan=" + ",".join(hex(x) for x in scan))
else:
    chip_id = i2c.readfrom_mem(BMP_ADDR, 0xD0, 1)[0]
    bmp = BMP280(i2c, BMP_ADDR)
    p0_sum = 0.0
    p0_n = 20
    for _ in range(p0_n):
        temp, pressure = bmp.read()
        p0_sum += pressure
        time.sleep_ms(100)
    p0 = p0_sum / p0_n

    print("BEGIN_BMP280_CSV")
    print("# label,%s" % LABEL)
    print("# sample_hz,%d" % SAMPLE_HZ)
    print("# duration_s,%d" % DURATION_S)
    print("# chip_id,0x%02X" % chip_id)
    print("# sda_gpio,%d" % SDA_PIN)
    print("# scl_gpio,%d" % SCL_PIN)
    print("# p0_pa,%.3f" % p0)
    print("t_ms,label,temp_c,pressure_pa,pressure_hpa,relative_alt_m")

    interval_ms = int(1000 / SAMPLE_HZ)
    total = SAMPLE_HZ * DURATION_S
    t0 = time.ticks_ms()
    next_t = t0
    for n in range(total):
        now = time.ticks_ms()
        temp, pressure = bmp.read()
        alt = pressure_to_altitude(pressure, p0)
        print("%d,%s,%.3f,%.3f,%.5f,%.4f" % (
            time.ticks_diff(now, t0), LABEL, temp, pressure, pressure / 100.0, alt
        ))
        next_t = time.ticks_add(next_t, interval_ms)
        wait_ms = time.ticks_diff(next_t, time.ticks_ms())
        if wait_ms > 0:
            time.sleep_ms(wait_ms)

    print("END_BMP280_CSV")
'''


def make_remote_code(label, duration_s):
    return (
        REMOTE_BMP_CODE
        .replace("__SAMPLE_HZ__", str(SAMPLE_HZ))
        .replace("__DURATION_S__", str(duration_s))
        .replace("__LABEL__", label)
    )


def capture_csv(ser, output_path, duration_s):
    rows = []
    in_csv = False
    last_progress = -1
    end_time = time.time() + duration_s + 45
    while time.time() < end_time:
        line = ser.readline().decode("utf-8", errors="replace").strip()
        if not line:
            continue
        print(line)
        if line.startswith("BMP280_ERROR"):
            raise RuntimeError(line)
        if line == "BEGIN_BMP280_CSV":
            in_csv = True
            continue
        if line == "END_BMP280_CSV":
            output_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
            return len(rows)
        if in_csv:
            rows.append(line)
            if not line.startswith("#") and not line.startswith("t_ms"):
                try:
                    elapsed_s = int(line.split(",", 1)[0]) // 1000
                except Exception:
                    continue
                progress = elapsed_s // 30
                if progress != last_progress:
                    print("  progress: %d/%d s" % (elapsed_s, duration_s))
                    last_progress = progress
    raise TimeoutError("BMP280 capture timed out.")


def main():
    data_dir = Path(__file__).resolve().parent / "data" / "bmp280"
    data_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    phases = [
        ("static", STATIC_DURATION_S, "静止气压噪声：板子放在桌面上，不要移动。"),
        ("height_change", MOTION_DURATION_S, "高度变化：缓慢把板子抬高/放低，或上下楼梯，动作尽量平稳。"),
    ]

    print("BMP280 pressure/temperature capture")
    print("Port:", COM_PORT)
    print("Sample rate:", SAMPLE_HZ, "Hz")
    print("The script will capture two phases: static and height_change.")
    input("Press Enter when the board is ready...")

    with serial.Serial(COM_PORT, BAUDRATE, timeout=1) as ser:
        for label, duration_s, instruction in phases:
            print("")
            print("Phase:", label)
            print("Duration:", duration_s, "s")
            print("Instruction:", instruction)
            input("Press Enter to start this phase...")
            output_path = data_dir / ("bmp280_%s_%s.csv" % (label, timestamp))
            start_remote_code(ser, make_remote_code(label, duration_s))
            rows = capture_csv(ser, output_path, duration_s)
            exit_raw_repl(ser)
            print("Saved %d lines to: %s" % (rows, output_path))

    print("Done. Next step: run analyze_bmp280.py")


if __name__ == "__main__":
    main()
