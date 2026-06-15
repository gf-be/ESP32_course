import time
import machine

PWM_PIN = 5
ADC_PIN = 4
PWM_FREQ = 1000
SAMPLES_PER_DUTY = 200

adc = machine.ADC(machine.Pin(ADC_PIN))
try:
    adc.atten(machine.ADC.ATTN_11DB)
except Exception:
    pass

pwm_pin = machine.Pin(PWM_PIN, machine.Pin.OUT)
pwm = machine.PWM(pwm_pin, freq=PWM_FREQ, duty_u16=0)

print("# board-only PWM to ADC loopback")
print("# wiring: GPIO%d -> GPIO%d" % (PWM_PIN, ADC_PIN))
print("# pwm_freq_hz,%d" % PWM_FREQ)
print("duty_percent,sample_index,elapsed_us,adc_u16,voltage_est_v")

start = time.ticks_us()
try:
    for duty_percent in (0, 25, 50, 75, 100):
        duty_u16 = int(65535 * duty_percent / 100)
        pwm.duty_u16(duty_u16)
        time.sleep_ms(100)
        for i in range(SAMPLES_PER_DUTY):
            raw = adc.read_u16()
            volts = raw * 3.3 / 65535
            print(
                "%d,%d,%d,%d,%.5f"
                % (duty_percent, i, time.ticks_diff(time.ticks_us(), start), raw, volts)
            )
            time.sleep_ms(2)
finally:
    pwm.deinit()
    pwm_pin.off()

