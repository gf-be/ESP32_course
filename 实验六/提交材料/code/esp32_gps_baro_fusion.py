"""
ESP32 MicroPython script for GPS and BMP280 barometric altitude logging.

The script is intended for outdoor/offline collection. It saves a new CSV file
on every run and does not overwrite existing data.

Output:
    /data/gps_baro/gps_baro_XXXX.csv
"""

from machine import I2C, Pin, UART
import os
import time


SDA_PIN = 21
SCL_PIN = 22
BMP280_ADDR = 0x76
GPS_RX_PIN = 16
GPS_TX_PIN = 17
GPS_BAUD = 9600
LED_PIN = 2

BARO_HZ = 5
DURATION_S = 900
ALPHA = 0.98


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
        self.write8(0xF4, 0x27)
        self.write8(0xF5, 0xA0)
        time.sleep_ms(100)

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


def nmea_latlon(value, hemi):
    if not value:
        return None
    raw = float(value)
    deg = int(raw // 100)
    minutes = raw - deg * 100
    dec = deg + minutes / 60.0
    if hemi in ("S", "W"):
        dec = -dec
    return dec


class GPSState:
    def __init__(self):
        self.utc = ""
        self.lat = None
        self.lon = None
        self.alt = None
        self.valid = 0
        self.satellites = 0
        self.hdop = -1.0
        self.speed_knots = -1.0
        self.course_deg = -1.0

    def update_line(self, line):
        if line.startswith("$GPGGA") or line.startswith("$GNGGA"):
            p = line.split(",")
            if len(p) >= 10:
                self.utc = p[1]
                fix = int(p[6] or "0")
                self.valid = 1 if fix > 0 else 0
                self.lat = nmea_latlon(p[2], p[3]) if p[2] else None
                self.lon = nmea_latlon(p[4], p[5]) if p[4] else None
                self.satellites = int(p[7] or "0")
                self.hdop = float(p[8] or "-1")
                self.alt = float(p[9]) if p[9] else None
        elif line.startswith("$GPRMC") or line.startswith("$GNRMC"):
            p = line.split(",")
            if len(p) >= 9:
                if p[2] == "A":
                    self.valid = 1
                    self.speed_knots = float(p[7] or "-1")
                    self.course_deg = float(p[8] or "-1")


def main():
    led = Pin(LED_PIN, Pin.OUT)
    i2c = I2C(0, scl=Pin(SCL_PIN), sda=Pin(SDA_PIN), freq=100000)
    sensor = BMP280(i2c)
    gps_uart = UART(2, baudrate=GPS_BAUD, rx=GPS_RX_PIN, tx=GPS_TX_PIN, timeout=0)
    gps = GPSState()

    p0_pa = mean_pressure(sensor)
    out_path = next_file("/data/gps_baro", "gps_baro")
    period_ms = int(1000 / BARO_HZ)
    end_ms = time.ticks_add(time.ticks_ms(), DURATION_S * 1000)
    gps_alt0 = None

    with open(out_path, "w") as f:
        f.write("# experiment,gps_baro_fusion\n")
        f.write("# chip_id,0x58\n")
        f.write("# p0_pa,%.3f\n" % p0_pa)
        f.write("# baro_hz,%d\n" % BARO_HZ)
        f.write("# alpha,%.3f\n" % ALPHA)
        f.write("t_ms,temp_c,pressure_pa,baro_alt_m,gps_valid,gps_utc,lat,lon,gps_alt_m,satellites,hdop,speed_knots,course_deg,fused_alt_m\n")
        f.flush()

        while time.ticks_diff(end_ms, time.ticks_ms()) > 0:
            while gps_uart.any():
                try:
                    line = gps_uart.readline()
                    if line:
                        gps.update_line(line.decode("ascii", "ignore").strip())
                except Exception:
                    pass

            temp_c, pressure_pa = sensor.read()
            baro_alt = altitude_m(pressure_pa, p0_pa)
            gps_alt = gps.alt if gps.valid and gps.alt is not None else None
            if gps_alt is not None and gps_alt0 is None:
                gps_alt0 = gps_alt
            if gps_alt is not None and gps_alt0 is not None:
                gps_rel = gps_alt - gps_alt0
                fused_alt = ALPHA * baro_alt + (1.0 - ALPHA) * gps_rel
                led.value(1)
            else:
                fused_alt = baro_alt
                led.value(1)
                time.sleep_ms(20)
                led.value(0)

            row = "%d,%.3f,%.3f,%.4f,%d,%s,%s,%s,%s,%d,%.2f,%.3f,%.2f,%.4f\n" % (
                time.ticks_ms(),
                temp_c,
                pressure_pa,
                baro_alt,
                gps.valid,
                gps.utc,
                "" if gps.lat is None else "%.8f" % gps.lat,
                "" if gps.lon is None else "%.8f" % gps.lon,
                "" if gps_alt is None else "%.3f" % gps_alt,
                gps.satellites,
                gps.hdop,
                gps.speed_knots,
                gps.course_deg,
                fused_alt,
            )
            f.write(row)
            f.flush()
            time.sleep_ms(period_ms)

    for _ in range(10):
        led.value(1)
        time.sleep_ms(100)
        led.value(0)
        time.sleep_ms(100)
    print("Done:", out_path)


main()
