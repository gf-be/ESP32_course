import machine
import sys
import time
import ubinascii


def main():
    print("hello_world.py running on ESP32 MicroPython")
    print("platform:", sys.platform)
    print("freq_hz:", machine.freq())
    print("unique_id:", ubinascii.hexlify(machine.unique_id()).decode())
    print("time_ms:", time.ticks_ms())


if __name__ == "__main__":
    main()
