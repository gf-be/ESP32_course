import time
from machine import Pin
from neopixel import NeoPixel


# The board used in this experiment is an ESP32-S3 board with a single
# onboard RGB LED connected to GPIO48. This keeps the official blink
# sample's purpose while adapting the LED driver to the actual board.
RGB_PIN = 48
PERIOD_MS = 500
BLINK_COUNT = 12


def main():
    pixel = NeoPixel(Pin(RGB_PIN, Pin.OUT), 1)
    print("blink.py started; RGB_PIN =", RGB_PIN)
    for i in range(BLINK_COUNT):
        pixel[0] = (0, 32, 0) if i % 2 == 0 else (0, 0, 0)
        pixel.write()
        print("blink step", i)
        time.sleep_ms(PERIOD_MS)
    pixel[0] = (0, 0, 0)
    pixel.write()
    print("blink.py done")


if __name__ == "__main__":
    main()
