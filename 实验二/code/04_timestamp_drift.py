import time
import machine

PERIOD_MS = 1000
DEFAULT_SAMPLES = 3600

print("# timestamp drift capture")
print("# columns: index,esp_ticks_ms,esp_ticks_us,cpu_freq_hz")
print("index,esp_ticks_ms,esp_ticks_us,cpu_freq_hz")

freq = machine.freq()
start = time.ticks_ms()
next_t = start
for i in range(DEFAULT_SAMPLES + 1):
    while time.ticks_diff(time.ticks_ms(), next_t) < 0:
        time.sleep_ms(5)
    print("%d,%d,%d,%d" % (i, time.ticks_ms(), time.ticks_us(), freq))
    next_t = time.ticks_add(next_t, PERIOD_MS)

