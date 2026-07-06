"""
ESP32 offline IMU + magnetometer + GPS logger for MicroPython.

Install this file to ESP32 as /main.py before the outdoor GPS/IMU experiment.
After power-bank power-on, it starts automatically and saves CSV chunks under
/imu_gps_logs. Nothing needs to stay connected to the computer during capture.

LED pattern on GPIO2:
- Boot: solid ON for START_LED_ON_S seconds, then three short ready flashes.
- Logging but no GPS NMEA yet: visible slow blink, 250 ms ON / 750 ms OFF.
- NMEA received but no usable GPS fix: visible 1 Hz blink, 500 ms ON / 500 ms OFF.
- Usable GPS fix and CSV is being saved: visible 2 Hz blink, 250 ms ON / 250 ms OFF.
- Error: fast blink.
"""

from machine import I2C, Pin, UART
import os
import struct
import time

try:
    import network
except Exception:
    network = None


SDA_PIN = 21
SCL_PIN = 22
I2C_FREQ = 400000
MPU_ADDR = 0x68
MAG_ADDR = 0x1E

GPS_UART_ID = 2
GPS_RX_PIN = 16       # GPS TX -> ESP32 GPIO16
GPS_TX_PIN = 17       # GPS RX -> ESP32 GPIO17, optional for receive-only use
GPS_BAUDRATE = 9600

STATUS_LED_PIN = 2
LED_ON_VALUE = 1      # Change to 0 if your LED is active-low.

SAMPLE_HZ = 20        # Flash-safe outdoor sync log rate for GPS/IMU ESKF.
CAPTURE_DURATION_S = 900
LOG_DIR = "/imu_gps_logs"
MAX_LINES_PER_FILE = 2000
FLUSH_EVERY_LINES = 20
STATUS_EVERY_S = 10
MIN_FREE_BYTES = 30000

START_LED_ON_S = 3
START_LED_OFF_S = 1

QUALITY_MIN_SATS = 4
QUALITY_MAX_HDOP = 5.0

CSV_HEADER = (
    "t_ms,ax_g,ay_g,az_g,temp_c,gx_dps,gy_dps,gz_dps,"
    "mx_raw,my_raw,mz_raw,gps_updated,gps_valid,gps_usable,"
    "fix_quality,satellites,hdop,gps_lat,gps_lon,gps_alt_m,"
    "gps_speed_mps,gps_course_deg,gps_utc,gps_date,"
    "nmea_count,fix_count,checksum_fail_count\n"
)


def ticks_ms():
    return time.ticks_ms()


def ticks_diff(a, b):
    return time.ticks_diff(a, b)


def ticks_add(t, delta):
    return time.ticks_add(t, delta)


def led_write(led, on):
    led.value(LED_ON_VALUE if on else 1 - LED_ON_VALUE)


def startup_ready_flash(led):
    for _ in range(3):
        led_write(led, True)
        time.sleep_ms(120)
        led_write(led, False)
        time.sleep_ms(160)


def update_status_led(led, mode, now, t0):
    # mode 0: no NMEA, mode 1: NMEA/no usable fix, mode 2: usable fix.
    elapsed = ticks_diff(now, t0)
    if mode <= 0:
        # The logger is alive and writing IMU/mag rows, but GPS bytes have not
        # arrived recently. Keep the blink visible so field checks are easy.
        led_write(led, elapsed % 1000 < 250)
    elif mode == 1:
        led_write(led, elapsed % 1000 < 500)
    else:
        led_write(led, elapsed % 500 < 250)


def error_blink(led):
    state = False
    while True:
        state = not state
        led_write(led, state)
        time.sleep_ms(120)


def wifi_off():
    if network is None:
        return
    for iface in (network.STA_IF, network.AP_IF):
        try:
            wlan = network.WLAN(iface)
            wlan.active(False)
        except Exception:
            pass


def ensure_dir(path):
    try:
        os.mkdir(path)
    except OSError:
        pass


def list_dir(path):
    try:
        return os.listdir(path)
    except OSError:
        return []


def flash_free_bytes():
    try:
        vfs = os.statvfs("/")
        return int(vfs[0]) * int(vfs[3])
    except Exception:
        return -1


def next_session_index():
    ensure_dir(LOG_DIR)
    max_index = 0
    for name in list_dir(LOG_DIR):
        if not name.startswith("imu_gps_sync_") or not name.endswith(".csv"):
            continue
        parts = name.split("_")
        if len(parts) < 5:
            continue
        try:
            index = int(parts[3])
        except Exception:
            index = 0
        if index > max_index:
            max_index = index
    return max_index + 1


def log_path(session_index, part_index):
    return LOG_DIR + "/imu_gps_sync_%04d_%02d.csv" % (session_index, part_index)


def write_header(f, path, session_index, part_index):
    f.write("# ESP32 offline IMU GPS sync logger\n")
    f.write("# log_path,%s\n" % path)
    f.write("# session_index,%d\n" % session_index)
    f.write("# part_index,%d\n" % part_index)
    f.write("# sample_hz,%d\n" % SAMPLE_HZ)
    f.write("# capture_duration_s,%d\n" % CAPTURE_DURATION_S)
    f.write("# i2c_sda_gpio,%d\n" % SDA_PIN)
    f.write("# i2c_scl_gpio,%d\n" % SCL_PIN)
    f.write("# gps_uart_id,%d\n" % GPS_UART_ID)
    f.write("# gps_rx_gpio,%d\n" % GPS_RX_PIN)
    f.write("# gps_tx_gpio,%d\n" % GPS_TX_PIN)
    f.write("# gps_baudrate,%d\n" % GPS_BAUDRATE)
    f.write(CSV_HEADER)
    f.flush()


def nmea_checksum_ok(sentence):
    if "*" not in sentence:
        return True
    try:
        body, checksum = sentence[1:].split("*", 1)
        calc = 0
        for ch in body:
            calc ^= ord(ch)
        return calc == int(checksum[:2], 16)
    except Exception:
        return False


def parse_latlon(value, hemi):
    if not value:
        return None
    raw = float(value)
    deg = int(raw // 100)
    minutes = raw - deg * 100
    out = deg + minutes / 60.0
    if hemi == "S" or hemi == "W":
        out = -out
    return out


class GPSParser:
    def __init__(self):
        self.lat = None
        self.lon = None
        self.alt = None
        self.sats = 0
        self.hdop = 99.0
        self.fix_quality = 0
        self.valid = False
        self.usable = False
        self.utc = ""
        self.date = ""
        self.speed_mps = None
        self.course_deg = None
        self.last_line_ms = -1000000
        self.last_fix_ms = -1000000
        self.nmea_count = 0
        self.fix_count = 0
        self.checksum_fail_count = 0
        self.line_buf = ""
        self.updated = 0

    def feed(self, line, now_ms):
        if not line or not line.startswith("$"):
            return False
        self.nmea_count += 1
        self.last_line_ms = now_ms
        if not nmea_checksum_ok(line):
            self.checksum_fail_count += 1
            return False
        parts = line.split("*", 1)[0].split(",")
        typ = parts[0]
        changed = False
        try:
            if typ.endswith("RMC") and len(parts) >= 10:
                self.utc = parts[1]
                self.date = parts[9]
                if parts[2] == "A":
                    lat = parse_latlon(parts[3], parts[4])
                    lon = parse_latlon(parts[5], parts[6])
                    if lat is not None and lon is not None:
                        self.lat = lat
                        self.lon = lon
                        self.speed_mps = float(parts[7]) * 0.514444 if parts[7] else 0.0
                        self.course_deg = float(parts[8]) if parts[8] else None
                        self.valid = True
                        changed = True
            elif typ.endswith("GGA") and len(parts) >= 10:
                self.utc = parts[1]
                self.fix_quality = int(parts[6]) if parts[6] else 0
                self.sats = int(parts[7]) if parts[7] else 0
                self.hdop = float(parts[8]) if parts[8] else 99.0
                if self.fix_quality > 0:
                    lat = parse_latlon(parts[2], parts[3])
                    lon = parse_latlon(parts[4], parts[5])
                    if lat is not None and lon is not None:
                        self.lat = lat
                        self.lon = lon
                        self.alt = float(parts[9]) if parts[9] else None
                        self.valid = True
                        self.last_fix_ms = now_ms
                        self.fix_count += 1
                        changed = True
        except Exception:
            return False

        self.usable = (
            self.valid
            and self.fix_quality > 0
            and self.sats >= QUALITY_MIN_SATS
            and self.hdop <= QUALITY_MAX_HDOP
        )
        if changed:
            self.updated = 1
        return changed


def read_gps_lines(uart, parser, now_ms):
    loops = 0
    while uart.any() and loops < 8:
        loops += 1
        n = uart.any()
        if n > 128:
            n = 128
        raw = uart.read(n)
        if not raw:
            continue
        try:
            parser.line_buf += raw.decode("ascii")
        except Exception:
            continue
        if len(parser.line_buf) > 768:
            parser.line_buf = parser.line_buf[-768:]

    lines = 0
    while "\n" in parser.line_buf and lines < 16:
        lines += 1
        line, parser.line_buf = parser.line_buf.split("\n", 1)
        parser.feed(line.strip(), now_ms)


def init_imu(i2c):
    i2c.writeto_mem(MPU_ADDR, 0x6B, b"\x00")
    time.sleep_ms(100)
    i2c.writeto_mem(MPU_ADDR, 0x1A, b"\x03")
    i2c.writeto_mem(MPU_ADDR, 0x1B, b"\x00")
    i2c.writeto_mem(MPU_ADDR, 0x1C, b"\x00")
    time.sleep_ms(100)


def init_mag(i2c):
    i2c.writeto_mem(MAG_ADDR, 0x00, b"\x70")
    i2c.writeto_mem(MAG_ADDR, 0x01, b"\x20")
    i2c.writeto_mem(MAG_ADDR, 0x02, b"\x00")
    time.sleep_ms(100)


def read_imu(i2c):
    raw = i2c.readfrom_mem(MPU_ADDR, 0x3B, 14)
    ax, ay, az, temp, gx, gy, gz = struct.unpack(">hhhhhhh", raw)
    return (
        ax / 16384.0,
        ay / 16384.0,
        az / 16384.0,
        temp / 340.0 + 36.53,
        gx / 131.0,
        gy / 131.0,
        gz / 131.0,
    )


def read_mag(i2c):
    raw = i2c.readfrom_mem(MAG_ADDR, 0x03, 6)
    x, z, y = struct.unpack(">hhh", raw)
    return x, y, z


def fmt_float(value, digits):
    if value is None:
        return ""
    try:
        return ("%." + str(digits) + "f") % value
    except Exception:
        return ""


def make_row(elapsed_ms, imu, mag, gps):
    if imu is None:
        imu_fields = ["", "", "", "", "", "", ""]
    else:
        imu_fields = [
            fmt_float(imu[0], 6),
            fmt_float(imu[1], 6),
            fmt_float(imu[2], 6),
            fmt_float(imu[3], 3),
            fmt_float(imu[4], 4),
            fmt_float(imu[5], 4),
            fmt_float(imu[6], 4),
        ]

    if mag is None:
        mag_fields = ["", "", ""]
    else:
        mag_fields = [str(mag[0]), str(mag[1]), str(mag[2])]

    if gps.updated:
        gps_fields = [
            "1",
            "1" if gps.valid else "0",
            "1" if gps.usable else "0",
            str(gps.fix_quality),
            str(gps.sats),
            fmt_float(gps.hdop, 2),
            fmt_float(gps.lat, 8),
            fmt_float(gps.lon, 8),
            fmt_float(gps.alt, 2),
            fmt_float(gps.speed_mps, 3),
            fmt_float(gps.course_deg, 2),
            gps.utc,
            gps.date,
        ]
        gps.updated = 0
    else:
        gps_fields = ["0", "", "", "", "", "", "", "", "", "", "", "", ""]

    gps_fields += [
        str(gps.nmea_count),
        str(gps.fix_count),
        str(gps.checksum_fail_count),
    ]

    fields = [str(elapsed_ms)] + imu_fields + mag_fields + gps_fields
    return ",".join(fields) + "\n"


def open_part(session_index, part_index):
    path = log_path(session_index, part_index)
    f = open(path, "w")
    write_header(f, path, session_index, part_index)
    print("opened:", path)
    return f, path


def main():
    status_led = Pin(STATUS_LED_PIN, Pin.OUT)
    led_write(status_led, False)

    led_write(status_led, True)
    time.sleep(START_LED_ON_S)
    led_write(status_led, False)
    time.sleep(START_LED_OFF_S)
    startup_ready_flash(status_led)

    wifi_off()

    i2c = I2C(0, sda=Pin(SDA_PIN), scl=Pin(SCL_PIN), freq=I2C_FREQ)
    scan = i2c.scan()
    print("ESP32 offline IMU GPS sync logger")
    print("I2C scan:", [hex(x) for x in scan])
    if MPU_ADDR not in scan or MAG_ADDR not in scan:
        print("sensor_missing,need MPU=0x68 MAG=0x1E")
        error_blink(status_led)

    init_imu(i2c)
    init_mag(i2c)
    uart = UART(
        GPS_UART_ID,
        baudrate=GPS_BAUDRATE,
        bits=8,
        parity=None,
        stop=1,
        rx=Pin(GPS_RX_PIN),
        tx=Pin(GPS_TX_PIN),
        timeout=0,
    )

    session_index = next_session_index()
    part_index = 1
    f, path = open_part(session_index, part_index)

    gps = GPSParser()
    t0 = ticks_ms()
    next_sample = t0
    last_status = t0
    period_ms = int(1000 / SAMPLE_HZ)
    line_count = 0
    total_lines = 0
    imu_fail_count = 0
    mag_fail_count = 0
    stop_reason = "duration"

    print("session:", session_index)
    print("sample_hz:", SAMPLE_HZ)
    print("duration_s:", CAPTURE_DURATION_S)
    print("log_dir:", LOG_DIR)
    print("LED: heartbeat=no GPS, slow blink=no fix, double flash=usable fix")

    try:
        while ticks_diff(ticks_ms(), t0) < CAPTURE_DURATION_S * 1000:
            now = ticks_ms()
            read_gps_lines(uart, gps, now)

            if ticks_diff(now, next_sample) >= 0:
                elapsed_ms = ticks_diff(now, t0)
                try:
                    imu = read_imu(i2c)
                except Exception:
                    imu = None
                    imu_fail_count += 1
                try:
                    mag = read_mag(i2c)
                except Exception:
                    mag = None
                    mag_fail_count += 1

                f.write(make_row(elapsed_ms, imu, mag, gps))
                line_count += 1
                total_lines += 1

                if line_count % FLUSH_EVERY_LINES == 0:
                    f.flush()

                if line_count >= MAX_LINES_PER_FILE:
                    f.write("# part_finished,lines,%d\n" % line_count)
                    f.flush()
                    f.close()
                    part_index += 1
                    line_count = 0
                    f, path = open_part(session_index, part_index)

                free = flash_free_bytes()
                if 0 <= free < MIN_FREE_BYTES:
                    stop_reason = "low_flash_free"
                    break

                next_sample = ticks_add(next_sample, period_ms)
                if ticks_diff(now, next_sample) > period_ms * 5:
                    next_sample = ticks_add(now, period_ms)

            if ticks_diff(now, gps.last_line_ms) > 3000:
                mode = 0
            elif gps.usable and ticks_diff(now, gps.last_fix_ms) <= 5000:
                mode = 2
            else:
                mode = 1
            update_status_led(status_led, mode, now, t0)

            if ticks_diff(now, last_status) >= STATUS_EVERY_S * 1000:
                elapsed_s = ticks_diff(now, t0) // 1000
                status = (
                    "# status,%d s,lines,%d,nmea,%d,fix,%d,sats,%d,hdop,%.2f,free,%d"
                    % (
                        elapsed_s,
                        total_lines,
                        gps.nmea_count,
                        gps.fix_count,
                        gps.sats,
                        gps.hdop,
                        flash_free_bytes(),
                    )
                )
                print(status)
                f.write(status + "\n")
                f.flush()
                last_status = now

            time.sleep_ms(2)

        f.write(
            "# finished,reason,%s,total_lines,%d,nmea,%d,fix,%d,imu_fail,%d,mag_fail,%d,free,%d\n"
            % (
                stop_reason,
                total_lines,
                gps.nmea_count,
                gps.fix_count,
                imu_fail_count,
                mag_fail_count,
                flash_free_bytes(),
            )
        )
        f.flush()
        f.close()

    except Exception as exc:
        try:
            f.write("# error,%s\n" % str(exc))
            f.flush()
            f.close()
        except Exception:
            pass
        print("logger_error:", exc)
        error_blink(status_led)

    print("logging_finished")
    print("session:", session_index)
    print("total_lines:", total_lines)
    print("nmea_count:", gps.nmea_count)
    print("fix_count:", gps.fix_count)

    # Finished signal: keep LED on if valid GPS was captured, off otherwise.
    led_write(status_led, gps.fix_count > 0)


try:
    main()
except Exception as exc:
    print("fatal_logger_error:", exc)
    try:
        error_blink(Pin(STATUS_LED_PIN, Pin.OUT))
    except Exception:
        raise
