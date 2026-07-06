"""
ESP32 power measurement stage runner for MicroPython.

Save this file to the ESP32 as /main.py, then measure input current with a
multimeter connected in series with the 5 V/VIN supply.

The program cycles through several fixed stages. Read the multimeter after the
stage has been running for about 10 seconds, then write the value in your table.
"""

from machine import I2C, Pin, UART
import math
import os
import time


SDA_PIN = 21
SCL_PIN = 22
I2C_FREQ = 400000

GPS_UART_ID = 2
GPS_RX_PIN = 16
GPS_TX_PIN = 17
GPS_BAUDRATE = 9600

LED_PIN = 2
LED_ON_VALUE = 1

STAGE_S = 60
GPS_STAGE_S = 120
WIFI_STAGE_S = 90
LOG_DIR = "/power_logs"

MPU_ADDR = 0x68
MAG_ADDR = 0x1E
BMP_ADDR = 0x76


def led(on):
    Pin(LED_PIN, Pin.OUT).value(LED_ON_VALUE if on else 1 - LED_ON_VALUE)


def blink(count, on_ms=120, off_ms=120):
    p = Pin(LED_PIN, Pin.OUT)
    for _ in range(count):
        p.value(LED_ON_VALUE)
        time.sleep_ms(on_ms)
        p.value(1 - LED_ON_VALUE)
        time.sleep_ms(off_ms)


def ensure_dir(path):
    try:
        os.mkdir(path)
    except OSError:
        pass


def next_log_path():
    ensure_dir(LOG_DIR)
    files = set(os.listdir(LOG_DIR))
    i = 1
    while True:
        name = "power_test_%04d.csv" % i
        if name not in files:
            return LOG_DIR + "/" + name
        i += 1


def stage_header(log, name, duration_s, note):
    print("")
    print("==== STAGE: %s ====" % name)
    print("duration_s:", duration_s)
    print("note:", note)
    print("Measure current after 10 seconds, then record the stable value.")
    log.write("%d,%s,start,%s\n" % (time.ticks_ms(), name, note))
    log.flush()
    blink(3)


def stage_footer(log, name, samples=0):
    print("==== END: %s samples=%d ====" % (name, samples))
    log.write("%d,%s,end,samples=%d\n" % (time.ticks_ms(), name, samples))
    log.flush()
    blink(2, 80, 80)


def init_i2c():
    return I2C(0, scl=Pin(SCL_PIN), sda=Pin(SDA_PIN), freq=I2C_FREQ)


def init_mpu(i2c):
    try:
        i2c.writeto_mem(MPU_ADDR, 0x6B, b"\x00")
        time.sleep_ms(100)
        i2c.writeto_mem(MPU_ADDR, 0x1B, b"\x00")
        i2c.writeto_mem(MPU_ADDR, 0x1C, b"\x00")
        return True
    except Exception as exc:
        print("MPU init failed:", exc)
        return False


def read_i16_be(buf, index):
    v = (buf[index] << 8) | buf[index + 1]
    if v & 0x8000:
        v -= 65536
    return v


def read_mpu(i2c):
    data = i2c.readfrom_mem(MPU_ADDR, 0x3B, 14)
    ax = read_i16_be(data, 0) / 16384.0
    ay = read_i16_be(data, 2) / 16384.0
    az = read_i16_be(data, 4) / 16384.0
    gx = read_i16_be(data, 8) / 131.0
    gy = read_i16_be(data, 10) / 131.0
    gz = read_i16_be(data, 12) / 131.0
    return ax, ay, az, gx, gy, gz


def init_mag(i2c):
    try:
        i2c.writeto_mem(MAG_ADDR, 0x00, b"\x70")
        i2c.writeto_mem(MAG_ADDR, 0x01, b"\x20")
        i2c.writeto_mem(MAG_ADDR, 0x02, b"\x00")
        return True
    except Exception as exc:
        print("MAG init failed:", exc)
        return False


def read_mag(i2c):
    data = i2c.readfrom_mem(MAG_ADDR, 0x03, 6)
    x = read_i16_be(data, 0)
    z = read_i16_be(data, 2)
    y = read_i16_be(data, 4)
    return x, y, z


def read_bmp_id(i2c):
    try:
        return i2c.readfrom_mem(BMP_ADDR, 0xD0, 1)[0]
    except Exception:
        return -1


def idle_stage(log, duration_s):
    name = "idle"
    stage_header(log, name, duration_s, "ESP32 powered, LED heartbeat only")
    t0 = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t0) < duration_s * 1000:
        led(True)
        time.sleep_ms(80)
        led(False)
        time.sleep_ms(1920)
    stage_footer(log, name, 0)


def sensor_stage(log, duration_s):
    name = "sensor_sampling"
    stage_header(log, name, duration_s, "I2C reads MPU + HMC + BMP ID")
    i2c = init_i2c()
    print("I2C scan:", [hex(x) for x in i2c.scan()])
    init_mpu(i2c)
    init_mag(i2c)
    bmp_id = read_bmp_id(i2c)
    print("BMP ID:", hex(bmp_id) if bmp_id >= 0 else "none")
    samples = 0
    t0 = time.ticks_ms()
    last = t0
    while time.ticks_diff(time.ticks_ms(), t0) < duration_s * 1000:
        try:
            read_mpu(i2c)
            read_mag(i2c)
            read_bmp_id(i2c)
            samples += 1
        except Exception as exc:
            print("sensor read failed:", exc)
        now = time.ticks_ms()
        if time.ticks_diff(now, last) >= 1000:
            print("sensor_sampling samples:", samples)
            led(samples % 2 == 0)
            last = now
        time.sleep_ms(5)
    led(False)
    stage_footer(log, name, samples)


def fusion_stage(log, duration_s):
    name = "attitude_fusion"
    stage_header(log, name, duration_s, "MPU read + complementary attitude update")
    i2c = init_i2c()
    init_mpu(i2c)
    roll = 0.0
    pitch = 0.0
    alpha = 0.98
    samples = 0
    t0 = time.ticks_ms()
    last = t0
    prev = t0
    while time.ticks_diff(time.ticks_ms(), t0) < duration_s * 1000:
        now = time.ticks_ms()
        dt = max(0.001, time.ticks_diff(now, prev) / 1000.0)
        prev = now
        try:
            ax, ay, az, gx, gy, gz = read_mpu(i2c)
            roll_acc = math.degrees(math.atan2(ay, az))
            pitch_acc = math.degrees(math.atan2(-ax, math.sqrt(ay * ay + az * az)))
            roll = alpha * (roll + gx * dt) + (1 - alpha) * roll_acc
            pitch = alpha * (pitch + gy * dt) + (1 - alpha) * pitch_acc
            samples += 1
        except Exception as exc:
            print("fusion read failed:", exc)
        if time.ticks_diff(now, last) >= 1000:
            print("fusion samples=%d roll=%.2f pitch=%.2f" % (samples, roll, pitch))
            led(samples % 2 == 0)
            last = now
        time.sleep_ms(5)
    led(False)
    stage_footer(log, name, samples)


def gps_stage(log, duration_s):
    name = "gps_on"
    stage_header(log, name, duration_s, "GPS UART powered and NMEA read")
    uart = UART(
        GPS_UART_ID,
        baudrate=GPS_BAUDRATE,
        bits=8,
        parity=None,
        stop=1,
        rx=Pin(GPS_RX_PIN),
        tx=Pin(GPS_TX_PIN),
        timeout=100,
    )
    lines = 0
    valid = 0
    t0 = time.ticks_ms()
    last = t0
    while time.ticks_diff(time.ticks_ms(), t0) < duration_s * 1000:
        raw = uart.readline()
        if raw:
            try:
                s = raw.decode("ascii").strip()
            except Exception:
                s = ""
            if s.startswith("$"):
                lines += 1
                parts = s.split("*", 1)[0].split(",")
                if parts[0].endswith("RMC") and len(parts) > 2 and parts[2] == "A":
                    valid += 1
                if parts[0].endswith("GGA") and len(parts) > 6 and parts[6] not in ("", "0"):
                    valid += 1
        now = time.ticks_ms()
        if time.ticks_diff(now, last) >= 1000:
            print("gps lines=%d valid=%d" % (lines, valid))
            led(lines % 2 == 0)
            last = now
    led(False)
    stage_footer(log, name, lines)


def wifi_stage(log, duration_s):
    name = "wifi_scan"
    stage_header(log, name, duration_s, "ESP32 WiFi active + repeated scan")
    samples = 0
    try:
        import network
        wlan = network.WLAN(network.STA_IF)
        wlan.active(True)
        time.sleep_ms(500)
        t0 = time.ticks_ms()
        last = t0
        while time.ticks_diff(time.ticks_ms(), t0) < duration_s * 1000:
            try:
                nets = wlan.scan()
                samples += 1
                print("wifi scan %d networks=%d" % (samples, len(nets)))
            except Exception as exc:
                print("wifi scan failed:", exc)
            led(True)
            time.sleep_ms(120)
            led(False)
            time.sleep_ms(1880)
            now = time.ticks_ms()
            if time.ticks_diff(now, last) >= 10000:
                log.write("%d,%s,status,scans=%d\n" % (now, name, samples))
                log.flush()
                last = now
        wlan.active(False)
    except Exception as exc:
        print("WiFi stage failed:", exc)
    led(False)
    stage_footer(log, name, samples)


def main():
    log_path = next_log_path()
    print("Power test program")
    print("Log:", log_path)
    print("Measure current with multimeter in series on 5V/VIN input.")
    print("Stages: idle, sensor_sampling, attitude_fusion, gps_on, wifi_scan")
    blink(8, 60, 60)
    time.sleep(3)

    with open(log_path, "w") as log:
        log.write("ticks_ms,stage,event,note\n")
        log.flush()
        idle_stage(log, STAGE_S)
        sensor_stage(log, STAGE_S)
        fusion_stage(log, STAGE_S)
        gps_stage(log, GPS_STAGE_S)
        wifi_stage(log, WIFI_STAGE_S)

    print("Power test finished.")
    print("Please copy your manual multimeter readings into the report table.")
    while True:
        blink(1, 500, 1500)


try:
    main()
except Exception as exc:
    print("Power test error:", exc)
    while True:
        blink(3, 80, 120)
        time.sleep(1)
