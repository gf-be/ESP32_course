#include <inttypes.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "driver/gpio.h"
#include "driver/ledc.h"
#include "driver/gptimer.h"
#include "esp_adc/adc_continuous.h"
#include "esp_adc/adc_oneshot.h"
#include "esp_err.h"
#include "esp_intr_alloc.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define PWM_GPIO GPIO_NUM_5
#define ADC_GPIO GPIO_NUM_4
#define ADC_UNIT ADC_UNIT_1
#define ADC_CHANNEL ADC_CHANNEL_3

#define IRQ_GPIO GPIO_NUM_6
#define IRQ_OUT_GPIO GPIO_NUM_7
#define IRQ_SAMPLES 10000
#define IRQ_PERIOD_US 1000

static volatile int64_t s_last_edge_time_us = 0;
static volatile int s_irq_index = 0;
static int16_t s_irq_lat_us[IRQ_SAMPLES];
static int16_t s_irq_interval_us[IRQ_SAMPLES];
static volatile int64_t s_last_irq_time_us = 0;

static void setup_pwm(void)
{
    ledc_timer_config_t timer = {
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .timer_num = LEDC_TIMER_0,
        .duty_resolution = LEDC_TIMER_10_BIT,
        .freq_hz = 1000,
        .clk_cfg = LEDC_AUTO_CLK,
    };
    ESP_ERROR_CHECK(ledc_timer_config(&timer));

    ledc_channel_config_t channel = {
        .gpio_num = PWM_GPIO,
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .channel = LEDC_CHANNEL_0,
        .intr_type = LEDC_INTR_DISABLE,
        .timer_sel = LEDC_TIMER_0,
        .duty = 512,
        .hpoint = 0,
    };
    ESP_ERROR_CHECK(ledc_channel_config(&channel));
}

static void run_adc_oneshot_polling(void)
{
    adc_oneshot_unit_handle_t unit = NULL;
    adc_oneshot_unit_init_cfg_t unit_cfg = {
        .unit_id = ADC_UNIT,
        .ulp_mode = ADC_ULP_MODE_DISABLE,
    };
    ESP_ERROR_CHECK(adc_oneshot_new_unit(&unit_cfg, &unit));

    adc_oneshot_chan_cfg_t chan_cfg = {
        .atten = ADC_ATTEN_DB_12,
        .bitwidth = ADC_BITWIDTH_DEFAULT,
    };
    ESP_ERROR_CHECK(adc_oneshot_config_channel(unit, ADC_CHANNEL, &chan_cfg));

    int64_t start = esp_timer_get_time();
    int64_t end = start + 1000000;
    int count = 0;
    int raw = 0;
    int64_t sum = 0;
    while (esp_timer_get_time() < end) {
        ESP_ERROR_CHECK(adc_oneshot_read(unit, ADC_CHANNEL, &raw));
        sum += raw;
        count++;
    }
    int64_t elapsed = esp_timer_get_time() - start;
    double rate = (double)count * 1000000.0 / (double)elapsed;
    double mean = count > 0 ? (double)sum / (double)count : 0.0;
    printf("ADC_POLL,count=%d,elapsed_us=%" PRId64 ",rate_hz=%.1f,cpu_load_percent=100.000,drop_percent=0.000,mean_raw=%.2f\n",
           count, elapsed, rate, mean);

    ESP_ERROR_CHECK(adc_oneshot_del_unit(unit));
}

static esp_err_t run_adc_dma_continuous(uint32_t sample_freq_hz)
{
    const uint32_t frame_bytes = 1024;
    const uint32_t max_store_bytes = 8192;

    adc_continuous_handle_t handle = NULL;
    adc_continuous_handle_cfg_t handle_cfg = {
        .max_store_buf_size = max_store_bytes,
        .conv_frame_size = frame_bytes,
    };
    esp_err_t ret = adc_continuous_new_handle(&handle_cfg, &handle);
    if (ret != ESP_OK) {
        printf("ADC_DMA,target_hz=%" PRIu32 ",error=new_handle_%s\n", sample_freq_hz, esp_err_to_name(ret));
        return ret;
    }

    adc_digi_pattern_config_t pattern = {
        .atten = ADC_ATTEN_DB_12,
        .channel = ADC_CHANNEL,
        .unit = ADC_UNIT,
        .bit_width = ADC_BITWIDTH_12,
    };
    adc_continuous_config_t cfg = {
        .sample_freq_hz = sample_freq_hz,
        .conv_mode = ADC_CONV_SINGLE_UNIT_1,
        .format = ADC_DIGI_OUTPUT_FORMAT_TYPE2,
        .pattern_num = 1,
        .adc_pattern = &pattern,
    };
    ret = adc_continuous_config(handle, &cfg);
    if (ret != ESP_OK) {
        printf("ADC_DMA,target_hz=%" PRIu32 ",error=config_%s\n", sample_freq_hz, esp_err_to_name(ret));
        adc_continuous_deinit(handle);
        return ret;
    }

    uint8_t buf[1024];
    uint32_t out_len = 0;
    uint32_t frames = 0;
    uint32_t bytes = 0;
    uint32_t samples = 0;
    uint32_t dropped_reads = 0;
    uint64_t active_us = 0;
    uint64_t raw_sum = 0;

    ret = adc_continuous_start(handle);
    if (ret != ESP_OK) {
        printf("ADC_DMA,target_hz=%" PRIu32 ",error=start_%s\n", sample_freq_hz, esp_err_to_name(ret));
        adc_continuous_deinit(handle);
        return ret;
    }
    int64_t start = esp_timer_get_time();
    int64_t end = start + 1000000;

    while (esp_timer_get_time() < end) {
        ret = adc_continuous_read(handle, buf, sizeof(buf), &out_len, 1000);
        int64_t active_start = esp_timer_get_time();
        if (ret == ESP_OK && out_len > 0) {
            frames++;
            bytes += out_len;
            for (uint32_t i = 0; i + sizeof(adc_digi_output_data_t) <= out_len; i += sizeof(adc_digi_output_data_t)) {
                adc_digi_output_data_t *p = (adc_digi_output_data_t *)&buf[i];
                raw_sum += p->type2.data;
                samples++;
            }
        } else {
            dropped_reads++;
        }
        active_us += (uint64_t)(esp_timer_get_time() - active_start);
    }
    int64_t elapsed = esp_timer_get_time() - start;
    ESP_ERROR_CHECK(adc_continuous_stop(handle));
    ESP_ERROR_CHECK(adc_continuous_deinit(handle));

    double measured_rate = (double)samples * 1000000.0 / (double)elapsed;
    double cpu = (double)active_us * 100.0 / (double)elapsed;
    double mean = samples ? (double)raw_sum / (double)samples : 0.0;
    double drop = dropped_reads ? (double)dropped_reads * 100.0 / (double)(dropped_reads + frames) : 0.0;

    printf("ADC_DMA,target_hz=%" PRIu32 ",samples=%" PRIu32 ",elapsed_us=%" PRId64 ",rate_hz=%.1f,cpu_load_percent=%.3f,drop_percent=%.3f,frames=%" PRIu32 ",mean_raw=%.2f\n",
           sample_freq_hz, samples, elapsed, measured_rate, cpu, drop, frames, mean);
    return ESP_OK;
}

static void IRAM_ATTR gpio_latency_isr(void *arg)
{
    int idx = s_irq_index;
    int64_t now = esp_timer_get_time();
    if (idx < IRQ_SAMPLES) {
        int64_t lat = now - s_last_edge_time_us;
        int64_t dt = idx == 0 ? 0 : now - s_last_irq_time_us;
        if (lat > 32767) {
            lat = 32767;
        }
        if (dt > 32767) {
            dt = 32767;
        }
        s_irq_lat_us[idx] = (int16_t)lat;
        s_irq_interval_us[idx] = (int16_t)dt;
        s_last_irq_time_us = now;
        s_irq_index = idx + 1;
    }
}

static void stats_print(const char *tag, const int16_t *vals, int start_index, int n)
{
    int min_v = vals[start_index];
    int max_v = vals[start_index];
    double sum = 0;
    for (int i = start_index; i < n; i++) {
        int v = vals[i];
        if (v < min_v) min_v = v;
        if (v > max_v) max_v = v;
        sum += v;
    }
    double mean = sum / (double)(n - start_index);
    double var = 0;
    for (int i = start_index; i < n; i++) {
        double d = (double)vals[i] - mean;
        var += d * d;
    }
    double std = sqrt(var / (double)(n - start_index));
    printf("%s,min_us=%d,max_us=%d,mean_us=%.3f,std_us=%.3f\n", tag, min_v, max_v, mean, std);
}

static void run_irq_priority_level(int level)
{
    memset((void *)s_irq_lat_us, 0, sizeof(s_irq_lat_us));
    memset((void *)s_irq_interval_us, 0, sizeof(s_irq_interval_us));
    s_irq_index = 0;
    s_last_irq_time_us = 0;

    gpio_config_t in_cfg = {
        .pin_bit_mask = 1ULL << IRQ_GPIO,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_ENABLE,
        .intr_type = GPIO_INTR_POSEDGE,
    };
    gpio_config_t out_cfg = {
        .pin_bit_mask = 1ULL << IRQ_OUT_GPIO,
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&in_cfg));
    ESP_ERROR_CHECK(gpio_config(&out_cfg));
    ESP_ERROR_CHECK(gpio_set_level(IRQ_OUT_GPIO, 0));

    int flags = ESP_INTR_FLAG_IRAM;
    if (level == 3) {
        flags |= ESP_INTR_FLAG_LEVEL3;
    } else {
        flags |= ESP_INTR_FLAG_LEVEL1;
    }
    ESP_ERROR_CHECK(gpio_install_isr_service(flags));
    ESP_ERROR_CHECK(gpio_isr_handler_add(IRQ_GPIO, gpio_latency_isr, NULL));

    vTaskDelay(pdMS_TO_TICKS(100));
    int64_t next = esp_timer_get_time() + 1000;
    for (int i = 0; i < IRQ_SAMPLES; i++) {
        while (esp_timer_get_time() < next) {
        }
        s_last_edge_time_us = esp_timer_get_time();
        gpio_set_level(IRQ_OUT_GPIO, 1);
        for (volatile int spin = 0; spin < 80; spin++) {
        }
        gpio_set_level(IRQ_OUT_GPIO, 0);
        next += IRQ_PERIOD_US;
    }
    int64_t deadline = esp_timer_get_time() + 1000000;
    while (s_irq_index < IRQ_SAMPLES && esp_timer_get_time() < deadline) {
        vTaskDelay(pdMS_TO_TICKS(1));
    }

    gpio_isr_handler_remove(IRQ_GPIO);
    gpio_uninstall_isr_service();
    ESP_ERROR_CHECK(gpio_set_level(IRQ_OUT_GPIO, 0));

    int captured = s_irq_index;
    double drop = (double)(IRQ_SAMPLES - captured) * 100.0 / (double)IRQ_SAMPLES;
    printf("IRQ_LEVEL%d,captured=%d,drop_percent=%.3f\n", level, captured, drop);
    if (captured > 10) {
        char tag[64];
        snprintf(tag, sizeof(tag), "IRQ_LEVEL%d_LATENCY", level);
        stats_print(tag, s_irq_lat_us, 1, captured);
        snprintf(tag, sizeof(tag), "IRQ_LEVEL%d_INTERVAL", level);
        stats_print(tag, s_irq_interval_us, 1, captured);
    }
}

void app_main(void)
{
    printf("\nEXPERIMENT2_IDF_DMA_IRQ_BEGIN\n");
    printf("WIRING,GPIO5_PWM_TO_GPIO4_ADC,GPIO7_OUT_TO_GPIO6_IRQ\n");
    setup_pwm();
    vTaskDelay(pdMS_TO_TICKS(200));
    run_adc_oneshot_polling();
    run_adc_dma_continuous(20000);
    run_adc_dma_continuous(50000);
    run_adc_dma_continuous(100000);
    run_irq_priority_level(1);
    vTaskDelay(pdMS_TO_TICKS(200));
    run_irq_priority_level(3);
    printf("EXPERIMENT2_IDF_DMA_IRQ_END\n");
}
