import time
import machine
import micropython
from array import array

micropython.alloc_emergency_exception_buf(100)

OUT_PIN = 5
IRQ_IN_PIN = 6
N = 10000
PERIOD_US = 1000
HIGH_US = 80

edge_times = array("I", [0] * N)
irq_times = array("I", [0] * N)
latencies = array("i", [0] * N)
edge_index = 0
irq_count = 0
armed = False

outp = machine.Pin(OUT_PIN, machine.Pin.OUT, value=0)
inp = machine.Pin(IRQ_IN_PIN, machine.Pin.IN, machine.Pin.PULL_DOWN)


def irq_cb(pin):
    global irq_count
    if not armed:
        return
    t = time.ticks_us()
    idx = irq_count
    if idx < N:
        irq_times[idx] = t
        latencies[idx] = time.ticks_diff(t, edge_times[idx])
        irq_count = idx + 1


inp.irq(trigger=machine.Pin.IRQ_RISING, handler=irq_cb)

print("# board-only GPIO interrupt loopback")
print("# wiring: GPIO%d -> GPIO%d" % (OUT_PIN, IRQ_IN_PIN))
print("# target_edges,%d" % N)
print("# target_period_us,%d" % PERIOD_US)
print("index,edge_time_us,irq_time_us,latency_us")

time.sleep_ms(1000)
armed = True
next_t = time.ticks_us()

for i in range(N):
    while time.ticks_diff(time.ticks_us(), next_t) < 0:
        pass
    edge_times[i] = time.ticks_us()
    outp.on()
    while time.ticks_diff(time.ticks_us(), edge_times[i]) < HIGH_US:
        pass
    outp.off()
    next_t = time.ticks_add(next_t, PERIOD_US)

deadline = time.ticks_add(time.ticks_ms(), 2000)
while irq_count < N and time.ticks_diff(deadline, time.ticks_ms()) > 0:
    time.sleep_ms(1)

armed = False
inp.irq(handler=None)
outp.off()

count = irq_count
for i in range(count):
    print("%d,%d,%d,%d" % (i, edge_times[i], irq_times[i], latencies[i]))

if count:
    vals = [latencies[i] for i in range(count)]
    mean = sum(vals) / len(vals)
    var = sum((x - mean) * (x - mean) for x in vals) / len(vals)
    print("# captured,%d" % count)
    print("# min_latency_us,%d" % min(vals))
    print("# max_latency_us,%d" % max(vals))
    print("# mean_latency_us,%.3f" % mean)
    print("# jitter_std_us,%.3f" % (var ** 0.5))
    print("# drop_rate_percent,%.3f" % ((N - count) * 100.0 / N))
else:
    print("# captured,0")

