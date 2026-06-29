"""
ESP32 MicroPython script for BMP280 staircase altitude sampling.

Usage:
1. Save this file as main.py on the ESP32 for offline sampling.
2. Power on the board and wait for the LED slow blink.
3. At each floor, keep the board still and press BOOT once.
4. The LED stays on while sampling. Move to the next floor after it blinks again.

Output files are saved on ESP32 flash under:
    /data/bmp280_staircase/staircase_esp32_XXXX.csv
"""

from machine import I2C, Pin
import os
import time


SDA_PIN = 21
SCL_PIN = 22
I2C_FREQ = 100000
BMP280_ADDR = 0x76
LED_PIN = 2
BOOT_PIN = 0

SAMPLE_HZ = 5
SAMPLE_SECONDS = 30
FLOOR_PLAN = [
    (1, "up"),
    (2, "up"),
    (3, "up"),
    (4, "up"),
    (5, "up"),
    (6, "up"),
    (6, "down"),
    (5, "down"),
    (4, "down"),
    (3, "down"),
    (2, "down"),
    (1, "down"),
]


def mkdir_p(path):
    parts = path.strip("/").split("/")
    cur = ""
    for part in parts:
        cur += "/" + part
        try:
            os.mkdir(cur)
        except OSError:
            pass


def next_file(path, prefix):
    mkdir_p(path)
    try:
        names = os.listdir(path)
    except OSError:
        names = []
    idx = 1
    while True:
        name = "%s_%04d.csv" % (prefix, idx)
        if name not in names:
            return path + "/" + name
        idx += 1


class BMP280:
    def __init__(self, i2c, addr=BMP280_ADDR):
        self.i2c = i2c
        self.addr = addr
        self.t_fine = 0
        chip_id = self.u8(0xD0)
        if chip_id != 0x58:
            raise RuntimeError("BMP280 chip_id expected 0x58, got 0x%02X" % chip_id)
        self.read_calibration()
        self.write8(0xF4, 0x27)  # temp and pressure oversampling x1, normal mode
        self.write8(0xF5, 0xA0)  # standby 1000 ms, filter off
        time.sleep_ms(100)

    def read_calibration(self):
        self.dig_T1 = self.u16(0x88)
        self.dig_T2 = self.s16(0x8A)
        self.dig_T3 = self.s16(0x8C)
        self.dig_P1 = self.u16(0x8E)
        self.dig_P2 = self.s16(0x90)
        self.dig_P3 = self.s16(0x92)
        self.dig_P4 = self.s16(0x94)
        self.dig_P5 = self.s16(0x96)
        self.dig_P6 = self.s16(0x98)
        self.dig_P7 = self.s16(0x9A)
        self.dig_P8 = self.s16(0x9C)
        self.dig_P9 = self.s16(0x9E)

    def write8(self, reg, val):
        self.i2c.writeto_mem(self.addr, reg, bytes([val & 0xFF]))

    def u8(self, reg):
        return self.i2c.readfrom_mem(self.addr, reg, 1)[0]

    def u16(self, reg):
        b = self.i2c.readfrom_mem(self.addr, reg, 2)
        return b[0] | (b[1] << 8)

    def s16(self, reg):
        v = self.u16(reg)
        return v - 65536 if v > 32767 else v

    def raw(self):
        b = self.i2c.readfrom_mem(self.addr, 0xF7, 6)
        adc_p = (b[0] << 12) | (b[1] << 4) | (b[2] >> 4)
        adc_t = (b[3] << 12) | (b[4] << 4) | (b[5] >> 4)
        return adc_t, adc_p

    def compensate_temperature(self, adc_t):
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
        adc_t, adc_p = self.raw()
        temp_c = self.compensate_temperature(adc_t)
        pressure_pa = self.compensate_pressure(adc_p)
        return temp_c, pressure_pa


def altitude_m(pressure_pa, p0_pa):
    return 44330.0 * (1.0 - (pressure_pa / p0_pa) ** 0.1903)


def mean_pressure(sensor, count=20):
    vals = []
    for _ in range(count):
        _, p = sensor.read()
        vals.append(p)
        time.sleep_ms(100)
    return sum(vals) / len(vals)


def wait_boot(button, led):
    print("Press BOOT to start this floor.")
    while button.value() == 0:
        time.sleep_ms(20)
    while button.value() == 1:
        led.value(1)
        time.sleep_ms(120)
        led.value(0)
        time.sleep_ms(380)
    time.sleep_ms(80)
    while button.value() == 0:
        time.sleep_ms(20)


def sample_floor(sensor, p0_pa, led):
    led.value(1)
    n = SAMPLE_HZ * SAMPLE_SECONDS
    temps = []
    pressures = []
    period_ms = int(1000 / SAMPLE_HZ)
    for _ in range(n):
        temp_c, pressure_pa = sensor.read()
        temps.append(temp_c)
        pressures.append(pressure_pa)
        time.sleep_ms(period_ms)
    led.value(0)
    pressure_mean = sum(pressures) / len(pressures)
    temp_mean = sum(temps) / len(temps)
    return {
        "samples": n,
        "temp_c": temp_mean,
        "pressure_pa": pressure_mean,
        "pressure_min_pa": min(pressures),
        "pressure_max_pa": max(pressures),
        "relative_alt_m": altitude_m(pressure_mean, p0_pa),
    }


def main():
    led = Pin(LED_PIN, Pin.OUT)
    button = Pin(BOOT_PIN, Pin.IN, Pin.PULL_UP)
    i2c = I2C(0, scl=Pin(SCL_PIN), sda=Pin(SDA_PIN), freq=I2C_FREQ)
    sensor = BMP280(i2c)
    p0_pa = mean_pressure(sensor)
    out_path = next_file("/data/bmp280_staircase", "staircase_esp32")

    with open(out_path, "w") as f:
        f.write("# experiment,bmp280_staircase\n")
        f.write("# chip_id,0x58\n")
        f.write("# sample_hz,%d\n" % SAMPLE_HZ)
        f.write("# sample_seconds,%d\n" % SAMPLE_SECONDS)
        f.write("# p0_pa,%.3f\n" % p0_pa)
        f.write("record_index,floor_hint,direction,samples,temp_c,pressure_pa,pressure_hpa,pressure_min_pa,pressure_max_pa,relative_alt_m\n")
        f.flush()

        for idx, (floor, direction) in enumerate(FLOOR_PLAN, 1):
            print("Record %02d floor=%s direction=%s" % (idx, floor, direction))
            wait_boot(button, led)
            rec = sample_floor(sensor, p0_pa, led)
            line = "%d,%d,%s,%d,%.3f,%.3f,%.5f,%.3f,%.3f,%.4f\n" % (
                idx,
                floor,
                direction,
                rec["samples"],
                rec["temp_c"],
                rec["pressure_pa"],
                rec["pressure_pa"] / 100.0,
                rec["pressure_min_pa"],
                rec["pressure_max_pa"],
                rec["relative_alt_m"],
            )
            f.write(line)
            f.flush()
            print(line.strip())

    for _ in range(8):
        led.value(1)
        time.sleep_ms(120)
        led.value(0)
        time.sleep_ms(120)
    print("Done:", out_path)


main()
