import sys
import time
import machine

try:
    import esp32
except ImportError:
    esp32 = None


print("# experiment2 board check")
print("key,value")
print("platform,%s" % sys.platform)
print("freq_hz,%d" % machine.freq())
print("unique_id,%s" % machine.unique_id().hex())

if esp32 and hasattr(esp32, "mcu_temperature"):
    print("mcu_temperature_c,%s" % esp32.mcu_temperature())
else:
    print("mcu_temperature_c,NA")

print("ticks_ms,%d" % time.ticks_ms())

