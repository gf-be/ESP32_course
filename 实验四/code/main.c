#include <stdint.h>
#include <stdio.h>
#include <math.h>
#include <stdbool.h>

#include "driver/i2c_master.h"
#include "esp_err.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define I2C_SDA_IO       GPIO_NUM_21
#define I2C_SCL_IO       GPIO_NUM_8
#define I2C_FREQ_HZ      50000
#define MPU_ADDR         0x68

#define REG_SMPLRT_DIV   0x19
#define REG_CONFIG       0x1A
#define REG_GYRO_CONFIG  0x1B
#define REG_ACCEL_CONFIG 0x1C
#define REG_ACCEL_XOUT_H 0x3B
#define REG_TEMP_OUT_H   0x41
#define REG_GYRO_XOUT_H  0x43
#define REG_PWR_MGMT_1   0x6B
#define REG_PWR_MGMT_2   0x6C
#define REG_WHO_AM_I     0x75

#define MPU6050_ID       0x68
#define MPU6500_ID       0x70
#define I2C_TIMEOUT_MS   100

#define OUTPUT_MODE_CSV      0
#define OUTPUT_MODE_ALLAN    1
#define OUTPUT_MODE_ATTITUDE 2
#define OUTPUT_MODE          OUTPUT_MODE_CSV

#define SAMPLE_PERIOD_MS     5
#define ATTITUDE_CAL_SAMPLES 400
#define ATTITUDE_PRINT_DIV   10
#define DEG_PER_RAD          57.2957795f

static const char *TAG = "LAB04";

static i2c_master_bus_handle_t i2c_bus;
static i2c_master_dev_handle_t mpu_dev;
static uint8_t mpu_who_am_i;

static const float ACCEL_A_INV[3][3] = {
    {0.99745688f, 0.00051362f, 0.05411571f},
    {-0.00911479f, 0.99783450f, 0.07146532f},
    {-0.05087812f, -0.06677926f, 0.97727439f},
};
static const float ACCEL_C_BIAS[3] = {0.00376301f, 0.00625345f, 0.01329749f};

static int16_t be16(const uint8_t *p) {
    return (int16_t)((p[0] << 8) | p[1]);
}

static float temp_c_from_raw(int16_t raw) {
    if (mpu_who_am_i == MPU6500_ID) {
        return (float)raw / 333.87f + 21.0f;
    }
    return (float)raw / 340.0f + 36.53f;
}

static float wrap_angle_deg(float angle) {
    while (angle > 180.0f) {
        angle -= 360.0f;
    }
    while (angle < -180.0f) {
        angle += 360.0f;
    }
    return angle;
}

static void correct_accel(float ax, float ay, float az, float *cx, float *cy, float *cz) {
    float v[3] = {
        ax - ACCEL_C_BIAS[0],
        ay - ACCEL_C_BIAS[1],
        az - ACCEL_C_BIAS[2],
    };
    *cx = ACCEL_A_INV[0][0] * v[0] + ACCEL_A_INV[0][1] * v[1] + ACCEL_A_INV[0][2] * v[2];
    *cy = ACCEL_A_INV[1][0] * v[0] + ACCEL_A_INV[1][1] * v[1] + ACCEL_A_INV[1][2] * v[2];
    *cz = ACCEL_A_INV[2][0] * v[0] + ACCEL_A_INV[2][1] * v[1] + ACCEL_A_INV[2][2] * v[2];
}

static esp_err_t mpu_write_byte(uint8_t reg, uint8_t value) {
    uint8_t buf[2] = {reg, value};
    return i2c_master_transmit(mpu_dev, buf, sizeof(buf), I2C_TIMEOUT_MS);
}

static esp_err_t mpu_read_bytes(uint8_t reg, uint8_t *data, size_t len) {
    return i2c_master_transmit_receive(mpu_dev, &reg, 1, data, len, I2C_TIMEOUT_MS);
}

static esp_err_t mpu_read_byte(uint8_t reg, uint8_t *value) {
    return mpu_read_bytes(reg, value, 1);
}

static void mpu_log_reg(uint8_t reg, const char *name) {
    uint8_t value = 0xff;
    esp_err_t err = mpu_read_byte(reg, &value);
    if (err == ESP_OK) {
        ESP_LOGI(TAG, "%s(0x%02X) = 0x%02X", name, reg, value);
    } else {
        ESP_LOGW(TAG, "%s(0x%02X) read failed: %s", name, reg, esp_err_to_name(err));
    }
}

static void mpu_dump_reg_range(uint8_t start, uint8_t end, const char *name) {
    ESP_LOGI(TAG, "Dump %s 0x%02X..0x%02X", name, start, end);
    for (uint8_t reg = start; reg <= end; ++reg) {
        uint8_t value = 0xff;
        esp_err_t err = mpu_read_byte(reg, &value);
        if (err == ESP_OK) {
            ESP_LOGI(TAG, "  reg[0x%02X] = 0x%02X", reg, value);
        } else {
            ESP_LOGW(TAG, "  reg[0x%02X] read failed: %s", reg, esp_err_to_name(err));
        }
        vTaskDelay(pdMS_TO_TICKS(5));
    }
}

static void mpu_prime_data_registers(void) {
    uint8_t value = 0;
    for (int pass = 0; pass < 8; ++pass) {
        for (uint8_t reg = REG_ACCEL_XOUT_H; reg <= REG_GYRO_XOUT_H + 5; ++reg) {
            (void)mpu_read_byte(reg, &value);
            vTaskDelay(pdMS_TO_TICKS(2));
        }
    }
}

static void mpu_try_write(uint8_t reg, uint8_t value, const char *name) {
    for (int i = 0; i < 3; ++i) {
        esp_err_t err = mpu_write_byte(reg, value);
        if (err == ESP_OK) {
            ESP_LOGI(TAG, "%s configured", name);
            return;
        }
        vTaskDelay(pdMS_TO_TICKS(20));
    }
    ESP_LOGW(TAG, "%s write skipped", name);
}

static void i2c_init(void) {
    i2c_master_bus_config_t bus_config = {
        .i2c_port = I2C_NUM_0,
        .sda_io_num = I2C_SDA_IO,
        .scl_io_num = I2C_SCL_IO,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };

    ESP_ERROR_CHECK(i2c_new_master_bus(&bus_config, &i2c_bus));

    i2c_device_config_t dev_config = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = MPU_ADDR,
        .scl_speed_hz = I2C_FREQ_HZ,
    };

    ESP_ERROR_CHECK(i2c_master_bus_add_device(i2c_bus, &dev_config, &mpu_dev));
}

static esp_err_t mpu_init(void) {
    uint8_t who = 0;
    esp_err_t err = mpu_read_byte(REG_WHO_AM_I, &who);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "WHO_AM_I read failed: %s", esp_err_to_name(err));
        return err;
    }

    ESP_LOGI(TAG, "WHO_AM_I = 0x%02X", who);
    if (who != MPU6050_ID && who != MPU6500_ID) {
        ESP_LOGE(TAG, "Unexpected device id. Check AD0/GND or module type.");
        return ESP_ERR_NOT_FOUND;
    }
    mpu_who_am_i = who;
    ESP_LOGI(TAG, "Compatible IMU detected, continuing with MPU60x0 register map.");

    mpu_try_write(REG_PWR_MGMT_1, 0x00, "PWR_MGMT_1 wake");  // wake up
    vTaskDelay(pdMS_TO_TICKS(100));
    mpu_try_write(REG_PWR_MGMT_2, 0x00, "PWR_MGMT_2 axes");   // enable gyro/accel axes
    mpu_try_write(REG_CONFIG, 0x03, "CONFIG DLPF");          // DLPF about 44 Hz
    mpu_try_write(REG_SMPLRT_DIV, 4, "SMPLRT_DIV");          // about 200 Hz internal sample
    mpu_try_write(REG_GYRO_CONFIG, 0x00, "GYRO_CONFIG");     // +/-250 deg/s
    mpu_try_write(REG_ACCEL_CONFIG, 0x00, "ACCEL_CONFIG");   // +/-2 g

    mpu_log_reg(REG_PWR_MGMT_1, "PWR_MGMT_1");
    mpu_log_reg(REG_PWR_MGMT_2, "PWR_MGMT_2");
    mpu_log_reg(REG_CONFIG, "CONFIG");
    mpu_log_reg(REG_SMPLRT_DIV, "SMPLRT_DIV");
    mpu_log_reg(REG_GYRO_CONFIG, "GYRO_CONFIG");
    mpu_log_reg(REG_ACCEL_CONFIG, "ACCEL_CONFIG");
    ESP_LOGI(TAG, "IMU ready on SDA=GPIO%d SCL=GPIO%d", I2C_SDA_IO, I2C_SCL_IO);
#if OUTPUT_MODE == OUTPUT_MODE_ALLAN
        puts("ALLAN,t,gz_dps");
#elif OUTPUT_MODE == OUTPUT_MODE_ATTITUDE
        puts("ATT,t,roll_deg,pitch_deg,roll_acc_deg,pitch_acc_deg,gx_dps,gy_dps,temp_c");
#else
        puts("CSV,t,ax_g,ay_g,az_g,gx_dps,gy_dps,gz_dps,temp_c");
#endif
    return ESP_OK;
}

void app_main(void) {
    i2c_init();
    ESP_LOGI(TAG, "I2C started: SDA=GPIO%d SCL=GPIO%d @ %d Hz",
             I2C_SDA_IO, I2C_SCL_IO, I2C_FREQ_HZ);

    while (mpu_init() != ESP_OK) {
        ESP_LOGW(TAG, "Retrying in 1s. Wiring target: VCC=3.3V, GND=GND, SDA=21, SCL=8, AD0=GND.");
        vTaskDelay(pdMS_TO_TICKS(1000));
    }

    TickType_t last_wake = xTaskGetTickCount();
#if OUTPUT_MODE == OUTPUT_MODE_ATTITUDE
    float roll = 0.0f;
    float pitch = 0.0f;
    float roll_zero = 0.0f;
    float pitch_zero = 0.0f;
    float gx_bias = 0.0f;
    float gy_bias = 0.0f;
    float roll_sum = 0.0f;
    float pitch_sum = 0.0f;
    float gx_sum = 0.0f;
    float gy_sum = 0.0f;
    int cal_count = 0;
    int print_count = 0;
    uint64_t last_us = esp_timer_get_time();
    bool attitude_ready = false;
    ESP_LOGI(TAG, "Attitude mode: keep the IMU still for %.1f seconds to zero roll/pitch.",
             (float)(ATTITUDE_CAL_SAMPLES * SAMPLE_PERIOD_MS) / 1000.0f);
#endif

    while (1) {
#if OUTPUT_MODE == OUTPUT_MODE_ALLAN
        uint8_t gyro_raw[6];
        esp_err_t err = mpu_read_bytes(REG_GYRO_XOUT_H, gyro_raw, sizeof(gyro_raw));
        if (err != ESP_OK) {
            static int read_failures = 0;
            if (++read_failures % 20 == 0) {
                ESP_LOGW(TAG, "MPU gyro read failed repeatedly: %s", esp_err_to_name(err));
            }
            vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(5));
            continue;
        }

        int16_t gz_raw = be16(&gyro_raw[4]);
        float t = (float)esp_timer_get_time() / 1000000.0f;
        float gz = (float)gz_raw / 131.0f;
        printf("ALLAN,%.6f,%.6f\n", t, gz);
        vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(SAMPLE_PERIOD_MS));
#else
        uint8_t accel_raw[6];
        uint8_t temp_raw_bytes[2];
        uint8_t gyro_raw[6];
        esp_err_t err = mpu_read_bytes(REG_ACCEL_XOUT_H, accel_raw, sizeof(accel_raw));
        if (err == ESP_OK) {
            err = mpu_read_bytes(REG_TEMP_OUT_H, temp_raw_bytes, sizeof(temp_raw_bytes));
        }
        if (err == ESP_OK) {
            err = mpu_read_bytes(REG_GYRO_XOUT_H, gyro_raw, sizeof(gyro_raw));
        }
        if (err != ESP_OK) {
            static int read_failures = 0;
            if (++read_failures % 20 == 0) {
                ESP_LOGW(TAG, "MPU read failed repeatedly: %s", esp_err_to_name(err));
            }
            vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(SAMPLE_PERIOD_MS));
            continue;
        }

        int16_t ax_raw = be16(&accel_raw[0]);
        int16_t ay_raw = be16(&accel_raw[2]);
        int16_t az_raw = be16(&accel_raw[4]);
        int16_t temp_raw = be16(&temp_raw_bytes[0]);
        int16_t gx_raw = be16(&gyro_raw[0]);
        int16_t gy_raw = be16(&gyro_raw[2]);
        int16_t gz_raw = be16(&gyro_raw[4]);

        float t = (float)esp_timer_get_time() / 1000000.0f;
        float ax = (float)ax_raw / 16384.0f;
        float ay = (float)ay_raw / 16384.0f;
        float az = (float)az_raw / 16384.0f;
        float temp = temp_c_from_raw(temp_raw);
        float gx = (float)gx_raw / 131.0f;
        float gy = (float)gy_raw / 131.0f;
        float gz = (float)gz_raw / 131.0f;
        float a_mag2 = ax * ax + ay * ay + az * az;

        if ((ax_raw == 0 && ay_raw == 0 && az_raw == 0 &&
             temp_raw == 0 && gx_raw == 0 && gy_raw == 0 && gz_raw == 0) ||
            a_mag2 < 0.16f || a_mag2 > 1.96f) {
            vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(SAMPLE_PERIOD_MS));
            continue;
        }

#if OUTPUT_MODE == OUTPUT_MODE_ATTITUDE
        float cax = 0.0f;
        float cay = 0.0f;
        float caz = 0.0f;
        correct_accel(ax, ay, az, &cax, &cay, &caz);

        float roll_acc = atan2f(cay, caz) * DEG_PER_RAD;
        float pitch_acc = atan2f(-cax, sqrtf(cay * cay + caz * caz)) * DEG_PER_RAD;

        if (!attitude_ready) {
            roll_sum += roll_acc;
            pitch_sum += pitch_acc;
            gx_sum += gx;
            gy_sum += gy;
            cal_count++;
            if (cal_count >= ATTITUDE_CAL_SAMPLES) {
                roll_zero = roll_sum / (float)cal_count;
                pitch_zero = pitch_sum / (float)cal_count;
                gx_bias = gx_sum / (float)cal_count;
                gy_bias = gy_sum / (float)cal_count;
                roll = 0.0f;
                pitch = 0.0f;
                last_us = esp_timer_get_time();
                attitude_ready = true;
                ESP_LOGI(TAG, "Attitude zero complete: roll0=%.2f pitch0=%.2f gx_bias=%.3f gy_bias=%.3f",
                         roll_zero, pitch_zero, gx_bias, gy_bias);
            }
            vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(SAMPLE_PERIOD_MS));
            continue;
        }

        uint64_t now_us = esp_timer_get_time();
        float dt = (float)(now_us - last_us) / 1000000.0f;
        last_us = now_us;
        if (dt <= 0.0f || dt > 0.1f) {
            dt = (float)SAMPLE_PERIOD_MS / 1000.0f;
        }

        float roll_acc_rel = wrap_angle_deg(roll_acc - roll_zero);
        float pitch_acc_rel = wrap_angle_deg(pitch_acc - pitch_zero);
        roll += (gx - gx_bias) * dt;
        pitch += (gy - gy_bias) * dt;
        roll = 0.98f * roll + 0.02f * roll_acc_rel;
        pitch = 0.98f * pitch + 0.02f * pitch_acc_rel;
        roll = wrap_angle_deg(roll);
        pitch = wrap_angle_deg(pitch);

        if (++print_count >= ATTITUDE_PRINT_DIV) {
            print_count = 0;
            printf("ATT,%.3f,%.2f,%.2f,%.2f,%.2f,%.3f,%.3f,%.2f\n",
                   t, roll, pitch, roll_acc_rel, pitch_acc_rel, gx - gx_bias, gy - gy_bias, temp);
        }
#else
        printf("CSV,%.3f,%.4f,%.4f,%.4f,%.3f,%.3f,%.3f,%.2f\n",
               t, ax, ay, az, gx, gy, gz, temp);
#endif

        vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(SAMPLE_PERIOD_MS));
#endif
    }
}
