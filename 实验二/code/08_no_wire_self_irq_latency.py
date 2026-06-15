import time
import machine
import micropython
from array import array

micropython.alloc_emergency_exception_buf(100)

PIN_NO = 5
N = 10000
PERIOD_US = 1000
HIGH_US = 80

latencies = array("h", [0] * N)
intervals = array("h", [0] * N)
irq_count = 0
armed = False
current_edge_us = 0
last_irq_us = 0

pin = machine.Pin(PIN_NO, machine.Pin.OUT, value=0)


def irq_cb(p):
    global irq_count, last_irq_us
    if not armed:
        return
    idx = irq_count
    if idx < N:
        now = time.ticks_us()
        latencies[idx] = time.ticks_diff(now, current_edge_us)
        if idx == 0:
            intervals[idx] = 0
        else:
            intervals[idx] = time.ticks_diff(now, last_irq_us)
        last_irq_us = now
        irq_count = idx + 1


pin.irq(trigger=machine.Pin.IRQ_RISING, handler=irq_cb)

print("# no-wire GPIO self interrupt latency")
print("# pin_gpio,%d" % PIN_NO)
print("# target_edges,%d" % N)
print("# target_period_us,%d" % PERIOD_US)
print("# note: same ESP32 pad is toggled by GPIO output and captured by GPIO interrupt")
print("index,latency_us,interval_us")

time.sleep_ms(1000)
armed = True
next_t = time.ticks_us()

for i in range(N):
    while time.ticks_diff(time.ticks_us(), next_t) < 0:
        pass
    current_edge_us = time.ticks_us()
    pin.on()
    while time.ticks_diff(time.ticks_us(), current_edge_us) < HIGH_US:
        pass
    pin.off()
    next_t = time.ticks_add(next_t, PERIOD_US)

deadline = time.ticks_add(time.ticks_ms(), 2000)
while irq_count < N and time.ticks_diff(deadline, time.ticks_ms()) > 0:
    time.sleep_ms(1)

armed = False
pin.irq(handler=None)
pin.off()

count = irq_count
for i in range(count):
    print("%d,%d,%d" % (i, latencies[i], intervals[i]))

if count:
    total = 0
    min_v = latencies[0]
    max_v = latencies[0]
    for i in range(count):
        v = latencies[i]
        total += v
        if v < min_v:
            min_v = v
        if v > max_v:
            max_v = v
    mean = total / count
    var_acc = 0
    for i in range(count):
        d = latencies[i] - mean
        var_acc += d * d
    var = var_acc / count
    print("# captured,%d" % count)
    print("# min_latency_us,%d" % min_v)
    print("# max_latency_us,%d" % max_v)
    print("# mean_latency_us,%.3f" % mean)
    print("# jitter_std_us,%.3f" % (var ** 0.5))
    print("# drop_rate_percent,%.3f" % ((N - count) * 100.0 / N))
    if count > 1:
        interval_total = 0
        interval_min = intervals[1]
        interval_max = intervals[1]
        for i in range(1, count):
            v = intervals[i]
            interval_total += v
            if v < interval_min:
                interval_min = v
            if v > interval_max:
                interval_max = v
        interval_mean = interval_total / (count - 1)
        interval_var_acc = 0
        for i in range(1, count):
            d = intervals[i] - interval_mean
            interval_var_acc += d * d
        interval_var = interval_var_acc / (count - 1)
        print("# interval_min_us,%d" % interval_min)
        print("# interval_max_us,%d" % interval_max)
        print("# interval_mean_us,%.3f" % interval_mean)
        print("# interval_jitter_std_us,%.3f" % (interval_var ** 0.5))
else:
    print("# captured,0")
