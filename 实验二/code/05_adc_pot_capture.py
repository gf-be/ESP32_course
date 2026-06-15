import time
import machine

ADC_PIN = 4
SAMPLE_HZ = 100
DURATION_S = 10

adc = machine.ADC(machine.Pin(ADC_PIN))
try:
    adc.atten(machine.ADC.ATTN_11DB)
except Exception:
    pass

period_us = 1000000 // SAMPLE_HZ
total = SAMPLE_HZ * DURATION_S
start = time.ticks_us()
next_t = start

print("# adc potentiometer capture")
print("# adc_pin,%d" % ADC_PIN)
print("# sample_hz,%d" % SAMPLE_HZ)
print("index,elapsed_us,adc_u16,voltage_est_v")

for i in range(total):
    while time.ticks_diff(time.ticks_us(), next_t) < 0:
        pass
    now = time.ticks_us()
    raw = adc.read_u16()
    volts = raw * 3.3 / 65535
    print("%d,%d,%d,%.5f" % (i, time.ticks_diff(now, start), raw, volts))
    next_t = time.ticks_add(next_t, period_us)

