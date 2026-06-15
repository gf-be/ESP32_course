import time
import machine

PWM_PIN = 5
ADC_PIN = 4
PWM_FREQ = 1000
SAMPLES = 1500
THRESHOLD = 30000

adc = machine.ADC(machine.Pin(ADC_PIN))
try:
    adc.atten(machine.ADC.ATTN_11DB)
except Exception:
    pass

pwm_pin = machine.Pin(PWM_PIN, machine.Pin.OUT)
pwm = machine.PWM(pwm_pin, freq=PWM_FREQ, duty_u16=0)

print("# board-only PWM to ADC loopback statistics")
print("# wiring: GPIO%d -> GPIO%d" % (PWM_PIN, ADC_PIN))
print("# pwm_freq_hz,%d" % PWM_FREQ)
print("# samples_per_duty,%d" % SAMPLES)
print("duty_percent,samples,min_adc,max_adc,mean_adc,mean_voltage_v,high_ratio_percent")

try:
    for duty_percent in (0, 25, 50, 75, 100):
        pwm.duty_u16(int(65535 * duty_percent / 100))
        time.sleep_ms(100)

        total = 0
        high = 0
        min_v = 65535
        max_v = 0
        delay = 37

        for _ in range(SAMPLES):
            raw = adc.read_u16()
            total += raw
            if raw > THRESHOLD:
                high += 1
            if raw < min_v:
                min_v = raw
            if raw > max_v:
                max_v = raw

            # Vary the sampling phase to avoid locking to the PWM period.
            delay = ((delay * 73 + 19) % 211) + 20
            time.sleep_us(delay)

        mean_adc = total / SAMPLES
        mean_v = mean_adc * 3.3 / 65535
        high_ratio = 100.0 * high / SAMPLES
        print(
            "%d,%d,%d,%d,%.2f,%.4f,%.2f"
            % (duty_percent, SAMPLES, min_v, max_v, mean_adc, mean_v, high_ratio)
        )
finally:
    pwm.deinit()
    pwm_pin.off()

