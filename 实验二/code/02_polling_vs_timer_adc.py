import time
import machine
import micropython
from array import array

micropython.alloc_emergency_exception_buf(100)

ADC_PIN = 4
TARGET_HZ = 1000
TIMER_N = 3000

adc = machine.ADC(machine.Pin(ADC_PIN))
try:
    adc.atten(machine.ADC.ATTN_11DB)
except Exception:
    pass


def adc_read():
    return adc.read_u16()


def polling_speed(duration_ms=1000):
    start = time.ticks_us()
    end = time.ticks_add(start, duration_ms * 1000)
    count = 0
    acc = 0
    while time.ticks_diff(end, time.ticks_us()) > 0:
        acc += adc_read()
        count += 1
    elapsed_us = time.ticks_diff(time.ticks_us(), start)
    return count, elapsed_us, acc


def polling_1khz(duration_ms=3000):
    period_us = 1000000 // TARGET_HZ
    start = time.ticks_us()
    next_t = start
    count = 0
    late = 0
    acc = 0
    while time.ticks_diff(time.ticks_us(), start) < duration_ms * 1000:
        while time.ticks_diff(time.ticks_us(), next_t) < 0:
            pass
        now = time.ticks_us()
        if time.ticks_diff(now, next_t) > period_us:
            late += 1
        acc += adc_read()
        count += 1
        next_t = time.ticks_add(next_t, period_us)
    elapsed_us = time.ticks_diff(time.ticks_us(), start)
    return count, elapsed_us, late, acc


timer_values = array("H", [0] * TIMER_N)
timer_dt = array("i", [0] * TIMER_N)
timer_service = array("i", [0] * TIMER_N)
timer_count = 0
timer_last = 0


def timer_cb(timer):
    global timer_count, timer_last
    t0 = time.ticks_us()
    if timer_count == 0:
        timer_last = t0
    if timer_count < TIMER_N:
        timer_values[timer_count] = adc_read()
        timer_dt[timer_count] = time.ticks_diff(t0, timer_last)
        timer_last = t0
        timer_service[timer_count] = time.ticks_diff(time.ticks_us(), t0)
        timer_count += 1


def timer_1khz():
    global timer_count, timer_last
    timer_count = 0
    timer_last = time.ticks_us()
    timer = machine.Timer(0)
    timer.init(freq=TARGET_HZ, mode=machine.Timer.PERIODIC, callback=timer_cb)
    start = time.ticks_ms()
    while timer_count < TIMER_N and time.ticks_diff(time.ticks_ms(), start) < 5000:
        time.sleep_ms(20)
    timer.deinit()
    elapsed_ms = time.ticks_diff(time.ticks_ms(), start)
    valid_dt = [timer_dt[i] for i in range(1, timer_count)]
    service_sum = sum(timer_service[i] for i in range(timer_count))
    return timer_count, elapsed_ms, valid_dt, service_sum


print("# adc polling and timer comparison")
print("# adc_pin,%d" % ADC_PIN)

speed_count, speed_us, _ = polling_speed(1000)
print("mode,max_rate_hz,cpu_load_est_percent,drop_rate_est_percent,samples,elapsed_ms")
print(
    "polling_tight,%.1f,100.0,0.0,%d,%.3f"
    % (speed_count * 1000000 / speed_us, speed_count, speed_us / 1000)
)

p_count, p_us, p_late, _ = polling_1khz(3000)
p_drop = 100.0 * p_late / p_count if p_count else 0
print(
    "polling_busywait_1khz,%.1f,100.0,%.3f,%d,%.3f"
    % (p_count * 1000000 / p_us, p_drop, p_count, p_us / 1000)
)

t_count, t_ms, valid_dt, service_sum = timer_1khz()
t_rate = t_count * 1000 / t_ms if t_ms else 0
t_cpu = 100.0 * service_sum / (t_ms * 1000) if t_ms else 0
t_drop = max(0, TIMER_N - t_count) * 100.0 / TIMER_N
print(
    "timer_irq_1khz,%.1f,%.3f,%.3f,%d,%d"
    % (t_rate, t_cpu, t_drop, t_count, t_ms)
)
if valid_dt:
    mean = sum(valid_dt) / len(valid_dt)
    var = sum((x - mean) * (x - mean) for x in valid_dt) / len(valid_dt)
    print("# timer_dt_min_us,%d" % min(valid_dt))
    print("# timer_dt_max_us,%d" % max(valid_dt))
    print("# timer_dt_mean_us,%.3f" % mean)
    print("# timer_dt_std_us,%.3f" % (var ** 0.5))

