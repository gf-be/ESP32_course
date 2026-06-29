from machine import Pin, I2C
import time


COMMON_I2C_PINS = [
    # Common ESP32 DevKit wiring
    (21, 22),
    # Common alternate wiring used by some examples/boards
    (18, 19),
    (25, 26),
    (32, 33),
]


KNOWN_DEVICES = {
    0x68: "MPU6050 / MPU9250 IMU",
    0x69: "MPU6050 alternate address",
    0x1E: "HMC5883L magnetometer",
    0x0D: "QMC5883L magnetometer",
    0x76: "BMP280 / MS5611 / BME280 pressure sensor",
    0x77: "BMP280 / MS5611 / BME280 pressure sensor",
}


def describe(addr):
    name = KNOWN_DEVICES.get(addr, "unknown device")
    return "0x%02X  %s" % (addr, name)


def scan_bus(sda_pin, scl_pin, freq=100000):
    print("\nScanning I2C: SDA=GPIO%d, SCL=GPIO%d, freq=%d Hz" % (sda_pin, scl_pin, freq))
    try:
        i2c = I2C(0, sda=Pin(sda_pin), scl=Pin(scl_pin), freq=freq)
        time.sleep_ms(100)
        devices = i2c.scan()
    except Exception as exc:
        print("  scan failed:", exc)
        return []

    if not devices:
        print("  no devices found")
        return []

    print("  found %d device(s):" % len(devices))
    for addr in devices:
        print("  -", describe(addr))
    return devices


def main():
    print("ESP32 I2C scanner")
    print("Expected for this project: MPU6050=0x68, HMC5883L=0x1E or QMC5883L=0x0D")

    found_any = False
    for sda_pin, scl_pin in COMMON_I2C_PINS:
        devices = scan_bus(sda_pin, scl_pin)
        found_any = found_any or bool(devices)

    print("\nDone.")
    if not found_any:
        print("No I2C devices were detected on the common pin pairs.")
        print("Check 3.3V/GND, SDA/SCL order, solder joints, and pull-up resistors.")


main()
