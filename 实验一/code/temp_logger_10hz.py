# Description: 采集温度数据

import gc
import time

try:
    import esp32
except ImportError:
    esp32 = None


SAMPLE_HZ = 10
DURATION_S = 30 * 60
OUTPUT_FILE = "temp_data.csv"


def read_temp_c():
    if esp32 is None:
        raise RuntimeError("esp32 module is not available")

    if hasattr(esp32, "mcu_temperature"):
        return float(esp32.mcu_temperature())

    if hasattr(esp32, "raw_temperature"):
        raw_f = float(esp32.raw_temperature())
        return (raw_f - 32.0) / 1.8

    raise RuntimeError("this firmware does not expose an internal temperature API")


def main():
    period_ms = int(1000 / SAMPLE_HZ)
    sample_count = int(DURATION_S * SAMPLE_HZ)
    start_ms = time.ticks_ms()

    print("temp_logger_10hz.py started")
    print("sample_hz =", SAMPLE_HZ)
    print("duration_s =", DURATION_S)
    print("output_file =", OUTPUT_FILE)

    with open(OUTPUT_FILE, "w") as f:
        f.write("sample,elapsed_s,temp_c\n")

        for sample in range(sample_count):
            target_ms = time.ticks_add(start_ms, sample * period_ms)
            wait_ms = time.ticks_diff(target_ms, time.ticks_ms())
            if wait_ms > 0:
                time.sleep_ms(wait_ms)

            now_ms = time.ticks_ms()
            elapsed_s = time.ticks_diff(now_ms, start_ms) / 1000.0
            temp_c = read_temp_c()

            f.write("{},{:.3f},{:.3f}\n".format(sample, elapsed_s, temp_c))
            if sample % SAMPLE_HZ == 0:
                f.flush()
                gc.collect()

            print("时间：{:.3f}s 温度：{:.2f} ℃".format(elapsed_s, temp_c))

    print("done; saved", OUTPUT_FILE)


if __name__ == "__main__":
    main()
