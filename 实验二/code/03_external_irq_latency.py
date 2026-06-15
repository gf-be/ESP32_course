import time
import machine
import micropython
from array import array

micropython.alloc_emergency_exception_buf(100)

IRQ_IN_PIN = 6
IRQ_MARK_PIN = 7
N = 10000

timestamps = array("I", [0] * N)
count = 0
armed = False

mark = machine.Pin(IRQ_MARK_PIN, machine.Pin.OUT, value=0)
inp = machine.Pin(IRQ_IN_PIN, machine.Pin.IN, machine.Pin.PULL_DOWN)


def irq_cb(pin):
    global count
    if not armed:
        return
    mark.on()
    if count < N:
        timestamps[count] = time.ticks_us()
        count += 1
    mark.off()


inp.irq(trigger=machine.Pin.IRQ_RISING, handler=irq_cb)

print("# external irq capture")
print("# input_pin_gpio,%d" % IRQ_IN_PIN)
print("# marker_pin_gpio,%d" % IRQ_MARK_PIN)
print("# requirement: feed GPIO%d with 0-3.3 V 1 kHz square wave and share GND" % IRQ_IN_PIN)
print("# optional oscilloscope: CH1=input, CH2=GPIO%d marker; CH2 rising edge is callback entry" % IRQ_MARK_PIN)
print("# waiting 2 s before arming")
time.sleep_ms(2000)

armed = True
start = time.ticks_ms()
while count < N and time.ticks_diff(time.ticks_ms(), start) < 15000:
    time.sleep_ms(20)
armed = False
inp.irq(handler=None)
mark.off()

print("# captured,%d" % count)
print("index,timestamp_us,interval_us")
prev = None
intervals = []
for i in range(count):
    ts = timestamps[i]
    if prev is None:
        dt = 0
    else:
        dt = time.ticks_diff(ts, prev)
        intervals.append(dt)
    print("%d,%d,%d" % (i, ts, dt))
    prev = ts

if intervals:
    mean = sum(intervals) / len(intervals)
    var = sum((x - mean) * (x - mean) for x in intervals) / len(intervals)
    print("# interval_min_us,%d" % min(intervals))
    print("# interval_max_us,%d" % max(intervals))
    print("# interval_mean_us,%.3f" % mean)
    print("# interval_jitter_std_us,%.3f" % (var ** 0.5))
    print("# note,software timestamps measure callback-arrival interval jitter, not absolute hardware latency")

