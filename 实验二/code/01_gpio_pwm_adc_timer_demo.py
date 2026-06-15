import time
import machine
import micropython
from array import array

micropython.alloc_emergency_exception_buf(100)

RGB_PIN = 48
PWM_PIN = 5
ADC_PIN = 4
TIMER_SAMPLES = 2000


def rgb_set(r, g, b):
    try:
        import neopixel
        np = neopixel.NeoPixel(machine.Pin(RGB_PIN, machine.Pin.OUT), 1)
        np[0] = (r, g, b)
        np.write()
        return True
    except Exception as exc:
        print("# rgb_unavailable,%s" % exc)
        return False


def run_board_rgb():
    ok = rgb_set(0, 0, 0)
    if not ok:
        return
    print("# gpio output: onboard RGB on GPIO48")
    for _ in range(3):
        rgb_set(40, 0, 0)
        time.sleep_ms(200)
        rgb_set(0, 0, 0)
        time.sleep_ms(200)
    print("# pwm-like breathing: onboard RGB brightness ramp")
    for _ in range(2):
        for v in range(0, 64, 4):
            rgb_set(0, 0, v)
            time.sleep_ms(20)
        for v in range(63, -1, -4):
            rgb_set(0, 0, v)
            time.sleep_ms(20)
    rgb_set(0, 0, 0)


def run_external_pwm():
    print("# hardware PWM output on GPIO%d; connect LED+resistor if available" % PWM_PIN)
    pin = machine.Pin(PWM_PIN, machine.Pin.OUT)
    pwm = machine.PWM(pin, freq=1000, duty_u16=0)
    for _ in range(2):
        for duty in range(0, 65536, 2048):
            pwm.duty_u16(duty)
            time.sleep_ms(10)
        for duty in range(65535, -1, -2048):
            pwm.duty_u16(duty)
            time.sleep_ms(10)
    pwm.deinit()
    pin.off()


def run_adc_preview():
    print("# adc preview on GPIO%d" % ADC_PIN)
    adc = machine.ADC(machine.Pin(ADC_PIN))
    try:
        adc.atten(machine.ADC.ATTN_11DB)
    except Exception:
        pass
    print("adc_index,ticks_ms,adc_u16,voltage_est_v")
    for i in range(20):
        raw = adc.read_u16()
        volts = raw * 3.3 / 65535
        print("%d,%d,%d,%.4f" % (i, time.ticks_ms(), raw, volts))
        time.sleep_ms(50)


intervals = array("i", [0] * TIMER_SAMPLES)
count = 0
last_us = 0


def timer_cb(timer):
    global count, last_us
    now = time.ticks_us()
    if count == 0:
        last_us = now
        count = 1
        return
    if count < TIMER_SAMPLES:
        intervals[count] = time.ticks_diff(now, last_us)
        last_us = now
        count += 1


def run_timer_jitter():
    global count, last_us
    print("# timer interrupt jitter, target 1000 Hz")
    count = 0
    last_us = time.ticks_us()
    timer = machine.Timer(0)
    timer.init(freq=1000, mode=machine.Timer.PERIODIC, callback=timer_cb)
    start = time.ticks_ms()
    while count < TIMER_SAMPLES and time.ticks_diff(time.ticks_ms(), start) < 4000:
        time.sleep_ms(10)
    timer.deinit()

    valid = [intervals[i] for i in range(1, count)]
    if valid:
        mean = sum(valid) / len(valid)
        min_v = min(valid)
        max_v = max(valid)
        var = sum((x - mean) * (x - mean) for x in valid) / len(valid)
        print("# timer_samples,%d" % len(valid))
        print("# timer_min_us,%d" % min_v)
        print("# timer_max_us,%d" % max_v)
        print("# timer_mean_us,%.3f" % mean)
        print("# timer_jitter_std_us,%.3f" % (var ** 0.5))
    else:
        print("# timer_no_samples")


run_board_rgb()
run_external_pwm()
run_adc_preview()
run_timer_jitter()
print("# demo done")

