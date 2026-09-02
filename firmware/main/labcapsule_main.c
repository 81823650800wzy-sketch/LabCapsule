#include <ctype.h>
#include <math.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "driver/gpio.h"
#include "driver/i2c_master.h"
#include "driver/ledc.h"
#include "driver/spi_master.h"
#include "driver/uart.h"
#include "driver/usb_serial_jtag.h"
#include "connectivity.h"
#include "device_config.h"
#include "esp_check.h"
#include "esp_err.h"
#include "esp_lcd_panel_commands.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_panel_vendor.h"
#include "esp_log.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "esp_mac.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "labcapsule_control.h"
#include "input_hub.h"
#include "media_store.h"
#include "offline_store.h"
#include "sensor_hub.h"
#include "wallpaper.h"

#define PIN_MPU_SDA                 GPIO_NUM_8
#define PIN_MPU_SCL                 GPIO_NUM_9
#define PIN_MPU_INT                 GPIO_NUM_2

#define PIN_TFT_SCLK                GPIO_NUM_12
#define PIN_TFT_MOSI                GPIO_NUM_11
#define PIN_TFT_CS                  GPIO_NUM_10
#define PIN_TFT_DC                  GPIO_NUM_7
#define PIN_TFT_RST                 GPIO_NUM_6
#define PIN_TFT_BL                  GPIO_NUM_5

#define PIN_BUTTON_UP               GPIO_NUM_14
#define PIN_BUTTON_DOWN             GPIO_NUM_15
#define PIN_BUTTON_LEFT             GPIO_NUM_16
#define PIN_BUTTON_RIGHT            GPIO_NUM_17
#define PIN_BUTTON_OK               GPIO_NUM_18
#define PIN_BUTTON_BACK             GPIO_NUM_13

#define TFT_WIDTH                   240
#define TFT_HEIGHT                  320
#define TFT_SPI_HOST                SPI2_HOST
#define DISPLAY_TRANSFER_ROWS       8
#define PET_BUBBLE_WIDTH            LABCAPSULE_PET_BUBBLE_WIDTH
#define PET_BUBBLE_HEIGHT           LABCAPSULE_PET_BUBBLE_HEIGHT
#define PET_BUBBLE_BYTES            LABCAPSULE_PET_BUBBLE_BYTES

#define MPU6050_ADDRESS_LOW         0x68
#define MPU6050_ADDRESS_HIGH        0x69
#define MPU6050_REG_SMPLRT_DIV      0x19
#define MPU6050_REG_CONFIG          0x1A
#define MPU6050_REG_GYRO_CONFIG     0x1B
#define MPU6050_REG_ACCEL_CONFIG    0x1C
#define MPU6050_REG_ACCEL_CONFIG2   0x1D
#define MPU6050_REG_ACCEL_XOUT_H    0x3B
#define MPU6050_REG_PWR_MGMT_1      0x6B
#define MPU6050_REG_WHO_AM_I        0x75

#define DEFAULT_SAMPLE_RATE_HZ      200U
#define DEFAULT_DURATION_SECONDS    10U
#define MIN_SAMPLE_RATE_HZ          10U
#define MAX_SAMPLE_RATE_HZ          500U
#define MAX_DURATION_SECONDS        3600U

#define SERIAL_LINE_CAPACITY        128
#define SERIAL_TX_CAPACITY          256

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

typedef enum {
    STATE_BOOT = 0,
    STATE_READY,
    STATE_RECORDING,
    STATE_COMPLETE,
    STATE_ABORTED,
    STATE_ERROR,
} device_state_t;

typedef struct {
    float ax;
    float ay;
    float az;
    float gx;
    float gy;
    float gz;
} motion_sample_t;

typedef enum {
    SERIAL_SOURCE_UART = 0,
    SERIAL_SOURCE_USB,
} serial_source_t;

typedef enum {
    SERIAL_UPLOAD_NONE = 0,
    SERIAL_UPLOAD_WALLPAPER,
    SERIAL_UPLOAD_CLIP,
    SERIAL_UPLOAD_PET_BUBBLE,
} serial_upload_kind_t;

typedef enum {
    DISPLAY_VIEW_STATUS = 0,
    DISPLAY_VIEW_SETTINGS,
    DISPLAY_VIEW_DEVELOPER,
    DISPLAY_VIEW_COLOR_TEST,
    DISPLAY_VIEW_WALLPAPER,
    DISPLAY_VIEW_MEDIA,
    DISPLAY_VIEW_IDLE,
    DISPLAY_VIEW_PET,
} display_view_t;

typedef struct {
    uint16_t base;
    uint16_t panel;
    uint16_t accent;
    uint16_t secondary;
    uint16_t text;
    uint16_t muted;
} visual_palette_t;

static const char *TAG = "LabCapsule";
static portMUX_TYPE s_state_lock = portMUX_INITIALIZER_UNLOCKED;

static volatile device_state_t s_state = STATE_BOOT;
static volatile uint32_t s_sample_rate_hz = DEFAULT_SAMPLE_RATE_HZ;
static volatile uint32_t s_duration_seconds = DEFAULT_DURATION_SECONDS;
static volatile uint32_t s_sample_count = 0;
static volatile int64_t s_recording_started_us = 0;
static volatile bool s_mock_enabled = false;
static volatile display_view_t s_display_view = DISPLAY_VIEW_STATUS;
static volatile uint8_t s_developer_page = 0;
static volatile uint32_t s_display_revision = 1;
static volatile bool s_idle_mode;
static char s_idle_title[20] = "DEVICE IDLE";
static char s_idle_message[36] = "READY FOR PHONE OR PC";
static char s_device_id[16];
static volatile bool s_host_link_active;
static volatile int64_t s_host_last_heartbeat_us;
static volatile uint8_t s_host_cpu_percent;
static volatile uint8_t s_host_ram_percent;
static volatile uint8_t s_host_disk_percent;
static volatile int16_t s_host_temperature_c = -1;
static uint8_t s_pet_bubble[PET_BUBBLE_BYTES];
static volatile bool s_pet_bubble_valid;
static char s_pet_emotion[12] = "IDLE";
static char s_pet_action[16] = "IDLE";
static volatile uint8_t s_pet_phase;

static bool s_usb_serial_ready = false;
static bool s_mpu_ready = false;
static SemaphoreHandle_t s_mpu_mutex;
static bool s_display_ready = false;
static bool s_display_inverted = false;
static bool s_backlight_commanded_on = false;
static bool s_backlight_pwm_ready = false;
static uint8_t s_backlight_brightness = 100;
static uint8_t s_visual_preset = 0;
static uint8_t s_wallpaper_opacity = 82;
static uint8_t s_panel_opacity = 76;
static uint8_t s_hud_opacity = 100;
static uint8_t s_mpu_address = MPU6050_ADDRESS_LOW;

static i2c_master_bus_handle_t s_i2c_bus = NULL;
static i2c_master_dev_handle_t s_mpu = NULL;
static esp_lcd_panel_handle_t s_panel = NULL;
/* Internal-RAM DMA staging blocks. Full frames remain in PSRAM. */
static uint16_t s_display_lines[2][TFT_WIDTH * DISPLAY_TRANSFER_ROWS];
static uint8_t s_display_line_index;
static uint16_t *s_framebuffers[2];
static uint16_t *s_media_canvas;
static const uint16_t *s_live_background_override;
static uint8_t s_render_buffer;
static SemaphoreHandle_t s_display_mutex;
static uint8_t *s_media_receive_buffer;
static size_t s_media_received;
static bool s_media_receive_active;
static uint32_t s_media_frame_duration_ms;
static uint16_t s_media_x;
static uint16_t s_media_y;
static uint16_t s_media_width;
static uint16_t s_media_height;
static labcapsule_media_encoding_t s_media_encoding;
static volatile bool s_media_clip_playing;
static volatile uint32_t s_media_clip_generation;
static volatile uint8_t s_media_clip_fps = 6;
static volatile serial_upload_kind_t s_serial_upload_kind;
static serial_source_t s_serial_upload_source;
static size_t s_serial_upload_expected;
static size_t s_serial_upload_received;
static uint32_t s_serial_upload_expected_crc;
static uint32_t s_serial_upload_crc;
static int64_t s_serial_upload_last_byte_us;

static const uint8_t FONT_ALPHA[26][5] = {
    {0x7e,0x11,0x11,0x11,0x7e}, {0x7f,0x49,0x49,0x49,0x36},
    {0x3e,0x41,0x41,0x41,0x22}, {0x7f,0x41,0x41,0x22,0x1c},
    {0x7f,0x49,0x49,0x49,0x41}, {0x7f,0x09,0x09,0x09,0x01},
    {0x3e,0x41,0x49,0x49,0x7a}, {0x7f,0x08,0x08,0x08,0x7f},
    {0x00,0x41,0x7f,0x41,0x00}, {0x20,0x40,0x41,0x3f,0x01},
    {0x7f,0x08,0x14,0x22,0x41}, {0x7f,0x40,0x40,0x40,0x40},
    {0x7f,0x02,0x0c,0x02,0x7f}, {0x7f,0x04,0x08,0x10,0x7f},
    {0x3e,0x41,0x41,0x41,0x3e}, {0x7f,0x09,0x09,0x09,0x06},
    {0x3e,0x41,0x51,0x21,0x5e}, {0x7f,0x09,0x19,0x29,0x46},
    {0x46,0x49,0x49,0x49,0x31}, {0x01,0x01,0x7f,0x01,0x01},
    {0x3f,0x40,0x40,0x40,0x3f}, {0x1f,0x20,0x40,0x20,0x1f},
    {0x3f,0x40,0x38,0x40,0x3f}, {0x63,0x14,0x08,0x14,0x63},
    {0x07,0x08,0x70,0x08,0x07}, {0x61,0x51,0x49,0x45,0x43},
};

static const uint8_t FONT_DIGIT[10][5] = {
    {0x3e,0x51,0x49,0x45,0x3e}, {0x00,0x42,0x7f,0x40,0x00},
    {0x42,0x61,0x51,0x49,0x46}, {0x21,0x41,0x45,0x4b,0x31},
    {0x18,0x14,0x12,0x7f,0x10}, {0x27,0x45,0x45,0x45,0x39},
    {0x3c,0x4a,0x49,0x49,0x30}, {0x01,0x71,0x09,0x05,0x03},
    {0x36,0x49,0x49,0x49,0x36}, {0x06,0x49,0x49,0x29,0x1e},
};

static uint16_t rgb565(uint8_t red, uint8_t green, uint8_t blue)
{
    uint16_t color = (uint16_t)(((red & 0xF8U) << 8) |
                                ((green & 0xFCU) << 3) |
                                (blue >> 3));
    return (uint16_t)((color << 8) | (color >> 8));
}

static const char *state_name(device_state_t state)
{
    switch (state) {
        case STATE_BOOT: return "BOOT";
        case STATE_READY: return "READY";
        case STATE_RECORDING: return "RECORDING";
        case STATE_COMPLETE: return "COMPLETE";
        case STATE_ABORTED: return "ABORTED";
        case STATE_ERROR: return "ERROR";
        default: return "UNKNOWN";
    }
}

static device_state_t get_state(void)
{
    device_state_t state;
    portENTER_CRITICAL(&s_state_lock);
    state = s_state;
    portEXIT_CRITICAL(&s_state_lock);
    return state;
}

static void set_state(device_state_t state)
{
    portENTER_CRITICAL(&s_state_lock);
    s_state = state;
    portEXIT_CRITICAL(&s_state_lock);
    sensor_hub_set_scan_enabled(state != STATE_RECORDING);
}

static void serial_emit(const char *format, ...)
{
    char buffer[SERIAL_TX_CAPACITY];
    va_list args;
    va_start(args, format);
    int length = vsnprintf(buffer, sizeof(buffer) - 3, format, args);
    va_end(args);

    if (length < 0) {
        return;
    }
    if (length > (int)sizeof(buffer) - 3) {
        length = (int)sizeof(buffer) - 3;
    }
    buffer[length++] = '\r';
    buffer[length++] = '\n';
    buffer[length] = '\0';

    uart_write_bytes(UART_NUM_0, buffer, (size_t)length);
    if (s_usb_serial_ready) {
        /* Never let an absent native-USB host throttle a 100-500 Hz experiment. */
        usb_serial_jtag_write_bytes(buffer, (size_t)length, 0);
    }
}

static esp_err_t serial_init(void)
{
    uart_config_t uart_config = {
        .baud_rate = 460800,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    ESP_RETURN_ON_ERROR(uart_param_config(UART_NUM_0, &uart_config), TAG, "UART config failed");
    ESP_RETURN_ON_ERROR(uart_set_pin(UART_NUM_0, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE,
                                     UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE), TAG,
                        "UART pin config failed");
    esp_err_t uart_result = uart_driver_install(UART_NUM_0, 16384, 0, 0, NULL, 0);
    if (uart_result != ESP_OK && uart_result != ESP_ERR_INVALID_STATE) {
        return uart_result;
    }

    usb_serial_jtag_driver_config_t usb_config = {
        .tx_buffer_size = 4096,
        .rx_buffer_size = 16384,
    };
    esp_err_t usb_result = usb_serial_jtag_driver_install(&usb_config);
    if (usb_result == ESP_OK || usb_result == ESP_ERR_INVALID_STATE) {
        s_usb_serial_ready = true;
    } else {
        ESP_LOGW(TAG, "USB Serial/JTAG unavailable: %s", esp_err_to_name(usb_result));
    }
    return ESP_OK;
}

static esp_err_t mpu_write_register(uint8_t reg, uint8_t value)
{
    uint8_t payload[2] = {reg, value};
    return i2c_master_transmit(s_mpu, payload, sizeof(payload), 100);
}

static esp_err_t mpu_read_registers(uint8_t reg, uint8_t *data, size_t length)
{
    return i2c_master_transmit_receive(s_mpu, &reg, 1, data, length, 100);
}

static esp_err_t mpu_set_sample_rate_unlocked(uint32_t rate_hz)
{
    if (!s_mpu_ready) {
        return ESP_ERR_INVALID_STATE;
    }
    uint32_t divider = (1000U / rate_hz);
    divider = divider > 0 ? divider - 1U : 0U;
    if (divider > 255U) {
        divider = 255U;
    }
    return mpu_write_register(MPU6050_REG_SMPLRT_DIV, (uint8_t)divider);
}

static esp_err_t mpu_probe_and_configure_unlocked(void)
{
    if (!s_i2c_bus) return ESP_ERR_INVALID_STATE;
    s_mpu_ready = false;
    if (s_mpu) {
        i2c_master_bus_rm_device(s_mpu);
        s_mpu = NULL;
    }
    if (i2c_master_probe(s_i2c_bus, MPU6050_ADDRESS_LOW, 100) == ESP_OK) {
        s_mpu_address = MPU6050_ADDRESS_LOW;
    } else if (i2c_master_probe(s_i2c_bus, MPU6050_ADDRESS_HIGH, 100) == ESP_OK) {
        s_mpu_address = MPU6050_ADDRESS_HIGH;
    } else {
        return ESP_ERR_NOT_FOUND;
    }

    i2c_device_config_t device_config = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = s_mpu_address,
        .scl_speed_hz = 400000,
    };
    ESP_RETURN_ON_ERROR(i2c_master_bus_add_device(s_i2c_bus, &device_config, &s_mpu),
                        TAG, "MPU6050 add-device failed");

    ESP_RETURN_ON_ERROR(mpu_write_register(MPU6050_REG_PWR_MGMT_1, 0x01), TAG,
                        "MPU6050 wake failed");
    vTaskDelay(pdMS_TO_TICKS(100));
    ESP_RETURN_ON_ERROR(mpu_write_register(MPU6050_REG_CONFIG, 0x03), TAG,
                        "MPU6050 DLPF config failed");
    ESP_RETURN_ON_ERROR(mpu_write_register(MPU6050_REG_GYRO_CONFIG, 0x08), TAG,
                        "MPU6050 gyro range config failed");
    ESP_RETURN_ON_ERROR(mpu_write_register(MPU6050_REG_ACCEL_CONFIG, 0x08), TAG,
                        "MPU6050 accel range config failed");
    ESP_RETURN_ON_ERROR(mpu_write_register(MPU6050_REG_ACCEL_CONFIG2, 0x03), TAG,
                        "MPU6050 accel filter config failed");

    uint8_t who_am_i = 0;
    ESP_RETURN_ON_ERROR(mpu_read_registers(MPU6050_REG_WHO_AM_I, &who_am_i, 1), TAG,
                        "MPU6050 identity read failed");
    if ((who_am_i & 0x7EU) != 0x68U) {
        ESP_LOGW(TAG, "Unexpected MPU6050 WHO_AM_I: 0x%02X", who_am_i);
    }
    s_mpu_ready = true;
    return mpu_set_sample_rate_unlocked(DEFAULT_SAMPLE_RATE_HZ);
}

static esp_err_t mpu_probe_and_configure(void)
{
    if (!s_mpu_mutex) return ESP_ERR_INVALID_STATE;
    xSemaphoreTake(s_mpu_mutex, portMAX_DELAY);
    esp_err_t result = mpu_probe_and_configure_unlocked();
    xSemaphoreGive(s_mpu_mutex);
    return result;
}

static esp_err_t mpu_set_sample_rate(uint32_t rate_hz)
{
    if (!s_mpu_mutex) return ESP_ERR_INVALID_STATE;
    xSemaphoreTake(s_mpu_mutex, portMAX_DELAY);
    esp_err_t result = mpu_set_sample_rate_unlocked(rate_hz);
    xSemaphoreGive(s_mpu_mutex);
    return result;
}

static esp_err_t mpu_init(void)
{
    i2c_master_bus_config_t bus_config = {
        .i2c_port = I2C_NUM_0,
        .sda_io_num = PIN_MPU_SDA,
        .scl_io_num = PIN_MPU_SCL,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    ESP_RETURN_ON_ERROR(i2c_new_master_bus(&bus_config, &s_i2c_bus), TAG,
                        "I2C bus init failed");
    if (!s_mpu_mutex) s_mpu_mutex = xSemaphoreCreateMutex();
    if (!s_mpu_mutex) return ESP_ERR_NO_MEM;
    esp_err_t result = ESP_ERR_NOT_FOUND;
    for (unsigned attempt = 0; attempt < 5 && result != ESP_OK; ++attempt) {
        if (attempt > 0) vTaskDelay(pdMS_TO_TICKS(250));
        result = mpu_probe_and_configure();
    }
    return result;
}

static esp_err_t mpu_read_sample(motion_sample_t *sample)
{
    uint8_t raw[14];
    if (!sample || !s_mpu_mutex) return ESP_ERR_INVALID_ARG;
    esp_err_t result = ESP_ERR_INVALID_STATE;
    xSemaphoreTake(s_mpu_mutex, portMAX_DELAY);
    for (unsigned attempt = 0; attempt < 3; ++attempt) {
        result = s_mpu ? mpu_read_registers(MPU6050_REG_ACCEL_XOUT_H, raw, sizeof(raw))
                       : ESP_ERR_INVALID_STATE;
        if (result == ESP_OK) break;
        vTaskDelay(pdMS_TO_TICKS(2));
    }
    xSemaphoreGive(s_mpu_mutex);
    if (result != ESP_OK) {
        ESP_LOGW(TAG, "MPU sample read retries failed: %s", esp_err_to_name(result));
        return result;
    }

    int16_t ax = (int16_t)((raw[0] << 8) | raw[1]);
    int16_t ay = (int16_t)((raw[2] << 8) | raw[3]);
    int16_t az = (int16_t)((raw[4] << 8) | raw[5]);
    int16_t gx = (int16_t)((raw[8] << 8) | raw[9]);
    int16_t gy = (int16_t)((raw[10] << 8) | raw[11]);
    int16_t gz = (int16_t)((raw[12] << 8) | raw[13]);

    sample->ax = (float)ax / 8192.0f;
    sample->ay = (float)ay / 8192.0f;
    sample->az = (float)az / 8192.0f;
    sample->gx = (float)gx / 65.5f;
    sample->gy = (float)gy / 65.5f;
    sample->gz = (float)gz / 65.5f;
    return ESP_OK;
}

static void make_mock_sample(int64_t timestamp_us, motion_sample_t *sample)
{
    float time_s = (float)timestamp_us / 1000000.0f;
    sample->ax = 0.04f * sinf(2.0f * (float)M_PI * 8.0f * time_s);
    sample->ay = 0.02f * sinf(2.0f * (float)M_PI * 13.0f * time_s);
    sample->az = 1.0f + 0.08f * sinf(2.0f * (float)M_PI * 8.0f * time_s);
    sample->gx = 1.5f * sinf(2.0f * (float)M_PI * 3.0f * time_s);
    sample->gy = 0.8f * cosf(2.0f * (float)M_PI * 4.0f * time_s);
    sample->gz = 0.4f * sinf(2.0f * (float)M_PI * 5.0f * time_s);
}

static esp_err_t display_fill_rect(int x, int y, int width, int height, uint16_t color)
{
    if (!s_panel || width <= 0 || height <= 0) {
        return ESP_ERR_INVALID_ARG;
    }
    if (x < 0) { width += x; x = 0; }
    if (y < 0) { height += y; y = 0; }
    if (x + width > TFT_WIDTH) width = TFT_WIDTH - x;
    if (y + height > TFT_HEIGHT) height = TFT_HEIGHT - y;
    if (width <= 0 || height <= 0) return ESP_OK;
    if (s_framebuffers[s_render_buffer]) {
        uint16_t *frame = s_framebuffers[s_render_buffer];
        for (int row = 0; row < height; ++row) {
            uint16_t *destination = frame + (y + row) * TFT_WIDTH + x;
            for (int column = 0; column < width; ++column) destination[column] = color;
        }
        return ESP_OK;
    }
    for (int row = 0; row < height; ++row) {
        uint16_t *line = s_display_lines[s_display_line_index];
        for (int i = 0; i < width; ++i) {
            line[i] = color;
        }
        esp_err_t result = esp_lcd_panel_draw_bitmap(s_panel, x, y + row,
                                                     x + width, y + row + 1, line);
        if (result != ESP_OK) {
            return result;
        }
        s_display_line_index ^= 1U;
    }
    return ESP_OK;
}

static uint16_t blend_rgb565(uint16_t background, uint16_t foreground, uint8_t opacity)
{
    if (opacity == 0) return background;
    if (opacity >= 100) return foreground;
    uint16_t bg = (uint16_t)((background << 8) | (background >> 8));
    uint16_t fg = (uint16_t)((foreground << 8) | (foreground >> 8));
    uint8_t bg_r = (uint8_t)(((bg >> 11) & 0x1FU) * 255U / 31U);
    uint8_t bg_g = (uint8_t)(((bg >> 5) & 0x3FU) * 255U / 63U);
    uint8_t bg_b = (uint8_t)((bg & 0x1FU) * 255U / 31U);
    uint8_t fg_r = (uint8_t)(((fg >> 11) & 0x1FU) * 255U / 31U);
    uint8_t fg_g = (uint8_t)(((fg >> 5) & 0x3FU) * 255U / 63U);
    uint8_t fg_b = (uint8_t)((fg & 0x1FU) * 255U / 31U);
    uint8_t red = (uint8_t)((bg_r * (100U - opacity) + fg_r * opacity) / 100U);
    uint8_t green = (uint8_t)((bg_g * (100U - opacity) + fg_g * opacity) / 100U);
    uint8_t blue = (uint8_t)((bg_b * (100U - opacity) + fg_b * opacity) / 100U);
    return rgb565(red, green, blue);
}

static esp_err_t display_fill_rect_alpha(int x, int y, int width, int height,
                                         uint16_t color, uint8_t opacity)
{
    if (!s_framebuffers[s_render_buffer] || opacity >= 100) {
        return display_fill_rect(x, y, width, height, color);
    }
    if (opacity == 0 || width <= 0 || height <= 0) return ESP_OK;
    if (x < 0) { width += x; x = 0; }
    if (y < 0) { height += y; y = 0; }
    if (x + width > TFT_WIDTH) width = TFT_WIDTH - x;
    if (y + height > TFT_HEIGHT) height = TFT_HEIGHT - y;
    if (width <= 0 || height <= 0) return ESP_OK;
    uint16_t *frame = s_framebuffers[s_render_buffer];
    for (int row = 0; row < height; ++row) {
        uint16_t *destination = frame + (y + row) * TFT_WIDTH + x;
        for (int column = 0; column < width; ++column) {
            destination[column] = blend_rgb565(destination[column], color, opacity);
        }
    }
    return ESP_OK;
}

static visual_palette_t visual_palette(void)
{
    if (s_visual_preset == 1) {
        return (visual_palette_t){
            .base = rgb565(22, 10, 13), .panel = rgb565(26, 17, 18),
            .accent = rgb565(255, 76, 68), .secondary = rgb565(246, 218, 27),
            .text = rgb565(248, 242, 222), .muted = rgb565(176, 157, 151),
        };
    }
    if (s_visual_preset == 2) {
        return (visual_palette_t){
            .base = rgb565(5, 18, 24), .panel = rgb565(8, 29, 36),
            .accent = rgb565(40, 224, 230), .secondary = rgb565(190, 241, 57),
            .text = rgb565(235, 250, 244), .muted = rgb565(126, 174, 179),
        };
    }
    return (visual_palette_t){
        .base = rgb565(14, 14, 15), .panel = rgb565(22, 22, 21),
        .accent = rgb565(246, 216, 14), .secondary = rgb565(255, 76, 68),
        .text = rgb565(247, 243, 224), .muted = rgb565(169, 166, 151),
    };
}

static void display_prepare_background(uint16_t base)
{
    uint16_t *frame = s_framebuffers[s_render_buffer];
    bool loaded = false;
    if (s_wallpaper_opacity > 0 && frame && s_live_background_override) {
        memcpy(frame, s_live_background_override, WALLPAPER_PAYLOAD_BYTES);
        loaded = true;
    } else if (s_wallpaper_opacity > 0 && frame && wallpaper_available()) {
        loaded = wallpaper_read_frame(frame, WALLPAPER_PAYLOAD_BYTES) == ESP_OK;
    }
    if (!loaded) {
        display_fill_rect(0, 0, TFT_WIDTH, TFT_HEIGHT, base);
        return;
    }
    for (size_t pixel = 0; pixel < TFT_WIDTH * TFT_HEIGHT; ++pixel) {
        frame[pixel] = blend_rgb565(base, frame[pixel], s_wallpaper_opacity);
    }
}

static const uint8_t *font_glyph(char character)
{
    static const uint8_t blank[5] = {0, 0, 0, 0, 0};
    static const uint8_t dash[5] = {0x08,0x08,0x08,0x08,0x08};
    static const uint8_t dot[5] = {0x00,0x60,0x60,0x00,0x00};
    static const uint8_t colon[5] = {0x00,0x36,0x36,0x00,0x00};
    if (character >= 'a' && character <= 'z') {
        character = (char)toupper((unsigned char)character);
    }
    if (character >= 'A' && character <= 'Z') {
        return FONT_ALPHA[character - 'A'];
    }
    if (character >= '0' && character <= '9') {
        return FONT_DIGIT[character - '0'];
    }
    if (character == '-') return dash;
    if (character == '.') return dot;
    if (character == ':') return colon;
    return blank;
}

static void display_text(int x, int y, const char *text, int scale, uint16_t color)
{
    while (*text) {
        const uint8_t *glyph = font_glyph(*text++);
        for (int column = 0; column < 5; ++column) {
            for (int row = 0; row < 7; ++row) {
                if (glyph[column] & (1U << row)) {
                    display_fill_rect_alpha(x + column * scale, y + row * scale,
                                            scale, scale, color, s_hud_opacity);
                }
            }
        }
        x += 6 * scale;
    }
}

static void display_request_refresh(void)
{
    ++s_display_revision;
}

static void display_set_backlight(bool enabled)
{
    if (s_backlight_pwm_ready) {
        uint32_t duty = enabled ? (uint32_t)s_backlight_brightness * 255U / 100U : 0;
        ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0, duty);
        ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0);
    } else {
        gpio_set_level(PIN_TFT_BL, enabled ? 1 : 0);
    }
    s_backlight_commanded_on = enabled;
}

static esp_err_t display_init(void)
{
    gpio_config_t backlight_config = {
        .pin_bit_mask = 1ULL << PIN_TFT_BL,
        .mode = GPIO_MODE_OUTPUT,
    };
    ESP_RETURN_ON_ERROR(gpio_config(&backlight_config), TAG, "Backlight config failed");
    display_set_backlight(false);

    spi_bus_config_t bus_config = {
        .sclk_io_num = PIN_TFT_SCLK,
        .mosi_io_num = PIN_TFT_MOSI,
        .miso_io_num = GPIO_NUM_NC,
        .quadwp_io_num = GPIO_NUM_NC,
        .quadhd_io_num = GPIO_NUM_NC,
        .max_transfer_sz = TFT_WIDTH * TFT_HEIGHT * sizeof(uint16_t),
    };
    ESP_RETURN_ON_ERROR(spi_bus_initialize(TFT_SPI_HOST, &bus_config, SPI_DMA_CH_AUTO),
                        TAG, "Display SPI bus init failed");

    esp_lcd_panel_io_handle_t panel_io = NULL;
    esp_lcd_panel_io_spi_config_t io_config = {
        .dc_gpio_num = PIN_TFT_DC,
        .cs_gpio_num = PIN_TFT_CS,
        // Breadboard/Dupont wiring is much more reliable at 10 MHz than 20+ MHz.
        .pclk_hz = 10 * 1000 * 1000,
        .lcd_cmd_bits = 8,
        .lcd_param_bits = 8,
        .spi_mode = 0,
        .trans_queue_depth = 1,
    };
    ESP_RETURN_ON_ERROR(esp_lcd_new_panel_io_spi((esp_lcd_spi_bus_handle_t)TFT_SPI_HOST,
                                                  &io_config, &panel_io),
                        TAG, "Display panel IO init failed");

    esp_lcd_panel_dev_config_t panel_config = {
        .reset_gpio_num = PIN_TFT_RST,
        .rgb_ele_order = LCD_RGB_ELEMENT_ORDER_RGB,
        .bits_per_pixel = 16,
    };
    ESP_RETURN_ON_ERROR(esp_lcd_new_panel_st7789(panel_io, &panel_config, &s_panel),
                        TAG, "ST7789 driver init failed");
    ESP_RETURN_ON_ERROR(esp_lcd_panel_reset(s_panel), TAG, "ST7789 reset failed");
    ESP_RETURN_ON_ERROR(esp_lcd_panel_init(s_panel), TAG, "ST7789 init failed");
    ESP_RETURN_ON_ERROR(esp_lcd_panel_invert_color(s_panel, s_display_inverted), TAG,
                        "ST7789 inversion config failed");
    ESP_RETURN_ON_ERROR(esp_lcd_panel_disp_on_off(s_panel, true), TAG,
                        "ST7789 display-on failed");
    // Three visible pulses provide a wiring test even when SPI data is not working.
    for (int pulse = 0; pulse < 3; ++pulse) {
        display_set_backlight(true);
        vTaskDelay(pdMS_TO_TICKS(120));
        display_set_backlight(false);
        vTaskDelay(pdMS_TO_TICKS(120));
    }
    ledc_timer_config_t backlight_timer = {
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .duty_resolution = LEDC_TIMER_8_BIT,
        .timer_num = LEDC_TIMER_0,
        .freq_hz = 5000,
        .clk_cfg = LEDC_AUTO_CLK,
    };
    ESP_RETURN_ON_ERROR(ledc_timer_config(&backlight_timer), TAG,
                        "Backlight PWM timer failed");
    ledc_channel_config_t backlight_channel = {
        .gpio_num = PIN_TFT_BL,
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .channel = LEDC_CHANNEL_0,
        .timer_sel = LEDC_TIMER_0,
        .duty = 255,
        .hpoint = 0,
    };
    ESP_RETURN_ON_ERROR(ledc_channel_config(&backlight_channel), TAG,
                        "Backlight PWM channel failed");
    s_backlight_pwm_ready = true;
    display_set_backlight(true);
    s_display_mutex = xSemaphoreCreateMutex();
    for (size_t i = 0; i < 2; ++i) {
        s_framebuffers[i] = heap_caps_calloc(TFT_WIDTH * TFT_HEIGHT, sizeof(uint16_t),
                                             MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    }
    s_media_canvas = heap_caps_calloc(TFT_WIDTH * TFT_HEIGHT, sizeof(uint16_t),
                                      MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    s_media_receive_buffer = heap_caps_malloc(WALLPAPER_PAYLOAD_BYTES,
                                               MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!s_display_mutex || !s_framebuffers[0] || !s_framebuffers[1] || !s_media_canvas ||
        !s_media_receive_buffer) {
        ESP_LOGE(TAG, "PSRAM frame buffer allocation failed");
        return ESP_ERR_NO_MEM;
    }
    s_display_ready = true;
    return ESP_OK;
}

static esp_err_t display_present(void)
{
    if (!s_panel || !s_framebuffers[s_render_buffer]) return ESP_ERR_INVALID_STATE;
    const uint16_t *frame = s_framebuffers[s_render_buffer];
    for (int y = 0; y < TFT_HEIGHT; y += DISPLAY_TRANSFER_ROWS) {
        int rows = TFT_HEIGHT - y;
        if (rows > DISPLAY_TRANSFER_ROWS) rows = DISPLAY_TRANSFER_ROWS;
        uint16_t *block = s_display_lines[s_display_line_index];
        memcpy(block, frame + y * TFT_WIDTH,
               (size_t)rows * TFT_WIDTH * sizeof(uint16_t));
        esp_err_t result = esp_lcd_panel_draw_bitmap(s_panel, 0, y, TFT_WIDTH,
                                                      y + rows, block);
        if (result != ESP_OK) return result;
        s_display_line_index ^= 1U;
    }
    s_render_buffer ^= 1U;
    return ESP_OK;
}

static void display_render_state(device_state_t state)
{
    if (!s_display_ready) {
        return;
    }
    visual_palette_t theme = visual_palette();
    uint16_t accent = theme.accent;
    switch (state) {
        case STATE_RECORDING:
            accent = rgb565(255, 70, 70);
            break;
        case STATE_COMPLETE:
            accent = rgb565(70, 255, 145);
            break;
        case STATE_ABORTED:
            accent = rgb565(255, 190, 50);
            break;
        case STATE_ERROR:
            accent = rgb565(255, 90, 210);
            break;
        default:
            break;
    }
    display_prepare_background(theme.base);
    display_fill_rect_alpha(0, 0, TFT_WIDTH, 116, theme.panel, s_panel_opacity);
    display_fill_rect_alpha(12, 128, 216, 62, theme.panel, s_panel_opacity);
    display_fill_rect_alpha(12, 202, 216, 100, theme.panel, s_panel_opacity);
    for (int x = 0; x < TFT_WIDTH; x += 30) {
        display_fill_rect_alpha(x, 0, 18, 8, x % 60 ? theme.secondary : accent,
                                s_hud_opacity);
    }
    display_fill_rect_alpha(16, 22, 44, 20, accent, s_hud_opacity);
    display_text(21, 26, "LC", 2, theme.base);
    display_text(70, 23, "LAB CAPSULE", 3, theme.text);
    display_text(18, 70, "FIELD UNIT 01", 2, theme.muted);
    display_fill_rect_alpha(18, 104, 204, 3, accent, s_hud_opacity);
    display_text(24, 144, state_name(state), state == STATE_RECORDING ? 3 : 4, accent);
    display_text(24, 218, s_mpu_ready ? "MPU LINK OK" : "MPU LINK LOST", 2,
                 s_mpu_ready ? theme.text : theme.secondary);
    offline_store_info_t offline;
    offline_store_get_info(&offline);
    char storage_text[32];
    if (offline.recording && offline.current_samples > 0) {
        snprintf(storage_text, sizeof(storage_text), "CACHE %lu LIVE",
                 (unsigned long)offline.current_samples);
    } else {
        snprintf(storage_text, sizeof(storage_text), "LOCAL %lu RUNS",
                 (unsigned long)offline.sessions);
    }
    display_text(24, 246, storage_text, 2,
                 offline.full ? theme.secondary : theme.muted);

    char config_text[32];
    snprintf(config_text, sizeof(config_text), "%luHZ  %luSEC",
             (unsigned long)s_sample_rate_hz, (unsigned long)s_duration_seconds);
    display_text(24, 278, config_text, 2, theme.text);
}

static unsigned usage_percent(size_t total, size_t free_bytes)
{
    if (total == 0 || free_bytes >= total) return 0;
    return (unsigned)((total - free_bytes) * 100U / total);
}

static void display_render_idle(void)
{
    if (!s_display_ready) return;
    visual_palette_t theme = visual_palette();
    size_t internal_total = heap_caps_get_total_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    size_t internal_free = heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    size_t psram_total = heap_caps_get_total_size(MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    size_t psram_free = heap_caps_get_free_size(MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    offline_store_info_t offline;
    offline_store_get_info(&offline);
    char line[36];

    display_prepare_background(theme.base);
    display_fill_rect_alpha(0, 0, TFT_WIDTH, 78, theme.panel, s_panel_opacity);
    display_fill_rect_alpha(12, 90, 216, 64, theme.panel, s_panel_opacity);
    display_fill_rect_alpha(12, 166, 216, 138, theme.panel, s_panel_opacity);
    display_fill_rect_alpha(0, 0, TFT_WIDTH, 8, theme.accent, s_hud_opacity);
    display_text(16, 22, "IDLE DASH", 3, theme.text);
    snprintf(line, sizeof(line), "UP %lluSEC",
             (unsigned long long)(esp_timer_get_time() / 1000000ULL));
    display_text(16, 58, line, 1, theme.muted);

    display_text(20, 102, s_idle_title, 2, theme.accent);
    display_text(20, 136, s_idle_message, 1, theme.text);

    bool host_live = s_host_link_active &&
            esp_timer_get_time() - s_host_last_heartbeat_us < 5000000LL;
    if (host_live) {
        snprintf(line, sizeof(line), "PC CPU %uPCT", (unsigned)s_host_cpu_percent);
        display_text(20, 182, line, 2, theme.text);
        snprintf(line, sizeof(line), "RAM %uPCT  DISK %uPCT",
                 (unsigned)s_host_ram_percent, (unsigned)s_host_disk_percent);
        display_text(20, 212, line, 1, theme.text);
        if (s_host_temperature_c >= 0)
            snprintf(line, sizeof(line), "TEMP %dC  USB ONLINE", (int)s_host_temperature_c);
        else snprintf(line, sizeof(line), "USB HOST ONLINE");
        display_text(20, 236, line, 1, theme.secondary);
    } else {
        s_host_link_active = false;
        snprintf(line, sizeof(line), "RAM %uPCT  %luK FREE",
                 usage_percent(internal_total, internal_free),
                 (unsigned long)(internal_free / 1024U));
        display_text(20, 182, line, 1, theme.text);
        snprintf(line, sizeof(line), "PSRAM %uPCT  %luK FREE",
                 usage_percent(psram_total, psram_free),
                 (unsigned long)(psram_free / 1024U));
        display_text(20, 206, line, 1, theme.text);
        unsigned store_percent = offline.bytes_capacity == 0 ? 0 :
                (unsigned)(offline.bytes_used * 100ULL / offline.bytes_capacity);
        snprintf(line, sizeof(line), "STORE %uPCT  %lu RUNS", store_percent,
                 (unsigned long)offline.sessions);
        display_text(20, 230, line, 1, offline.full ? theme.secondary : theme.text);
    }
    snprintf(line, sizeof(line), "LINK B%d W%d M%d",
             connectivity_ble_connected() ? 1 : 0,
             connectivity_sta_connected() ? 1 : 0,
             connectivity_remote_connected() ? 1 : 0);
    display_text(20, 254, line, 2, theme.accent);
    display_text(20, 286, "OK EXPERIMENT", 2, theme.muted);
}

static bool pet_action_is(const char *value)
{
    return strcmp(s_pet_action, value) == 0;
}

static void display_render_pet_bubble(visual_palette_t theme)
{
    const int panel_x = 8;
    const int panel_y = 236;
    display_fill_rect_alpha(panel_x, panel_y, 224, 76, theme.text, 96);
    display_fill_rect_alpha(104, 228, 24, 12, theme.text, 96);
    if (!s_pet_bubble_valid) {
        display_text(28, 264, "ASK ME ANYTHING", 2, theme.base);
        return;
    }
    for (unsigned y = 0; y < PET_BUBBLE_HEIGHT; ++y) {
        unsigned x = 0;
        while (x < PET_BUBBLE_WIDTH) {
            unsigned bit = y * PET_BUBBLE_WIDTH + x;
            if ((s_pet_bubble[bit >> 3] & (0x80U >> (bit & 7U))) == 0) {
                ++x;
                continue;
            }
            unsigned start = x++;
            while (x < PET_BUBBLE_WIDTH) {
                bit = y * PET_BUBBLE_WIDTH + x;
                if ((s_pet_bubble[bit >> 3] & (0x80U >> (bit & 7U))) == 0) break;
                ++x;
            }
            display_fill_rect(panel_x + 4 + (int)start, panel_y + 6 + (int)y,
                              (int)(x - start), 1, theme.base);
        }
    }
}

static void display_render_pet(void)
{
    if (!s_display_ready) return;
    visual_palette_t theme = visual_palette();
    uint16_t accent = theme.accent;
    if (strcmp(s_pet_emotion, "WARNING") == 0 || pet_action_is("ALERT"))
        accent = rgb565(255, 76, 90);
    else if (strcmp(s_pet_emotion, "SUCCESS") == 0 || pet_action_is("CELEBRATE"))
        accent = rgb565(74, 232, 128);
    else if (strcmp(s_pet_emotion, "THINKING") == 0 || pet_action_is("THINK"))
        accent = rgb565(96, 165, 250);

    int bob = (pet_action_is("BOUNCE") || pet_action_is("CELEBRATE"))
            ? (int)(s_pet_phase % 4U) - 2 : (int)(s_pet_phase & 1U);
    int body_x = pet_action_is("TILT") ? 58 + (int)(s_pet_phase % 3U) : 60;
    int body_y = 64 + bob;
    const labcapsule_config_t *config = device_config_get();
    bool proxy = config->pet_proxy_enabled && s_media_clip_playing &&
            media_store_clip_available() && s_media_canvas;
    const uint16_t *previous_background = s_live_background_override;
    if (proxy) s_live_background_override = s_media_canvas;
    display_prepare_background(theme.base);
    s_live_background_override = previous_background;
    if (proxy) {
        /* The host rendered the canonical Live2D model.  Keep the full image and
         * add only lightweight device-side state cues plus the dialogue bubble. */
        display_fill_rect_alpha(7, 7, 226, 3, accent, 82);
        display_fill_rect_alpha(7, 10, 3, 208, accent, 52);
        if (pet_action_is("THINK") || pet_action_is("SCAN")) {
            for (int index = 0; index < 4; ++index)
                display_fill_rect(190 + index * 8, 24 + ((s_pet_phase + index * 3U) % 18U),
                                  4, 4, accent);
        } else if (pet_action_is("CELEBRATE") || strcmp(s_pet_emotion, "SUCCESS") == 0) {
            display_fill_rect(20, 30 + (s_pet_phase % 28U), 6, 6, theme.secondary);
            display_fill_rect(212, 58 - (s_pet_phase % 24U), 6, 6, accent);
        } else if (pet_action_is("ALERT") || strcmp(s_pet_emotion, "WARNING") == 0) {
            display_fill_rect_alpha(10, 12, 220, 8, theme.secondary,
                                    (s_pet_phase / 2U) % 2U ? 80 : 28);
        }
        display_render_pet_bubble(theme);
        return;
    }
    display_fill_rect_alpha(0, 0, TFT_WIDTH, 42, theme.panel, 94);
    display_fill_rect_alpha(0, 0, TFT_WIDTH, 6, accent, 100);
    display_text(12, 16, "PET LINK", 2, theme.text);
    display_text(136, 18, s_pet_emotion, 1, accent);

    display_fill_rect_alpha(body_x - 8, body_y + 28, 136, 116, accent, 100);
    display_fill_rect_alpha(body_x, body_y + 20, 120, 132, accent, 100);
    display_fill_rect_alpha(body_x + 6, body_y + 26, 108, 120, theme.panel, 100);
    display_fill_rect_alpha(body_x + 14, body_y + 44, 92, 70, theme.base, 92);
    display_fill_rect_alpha(body_x - 22, body_y + 82, 20, 8, accent, 100);
    display_fill_rect_alpha(body_x + 122, body_y + 82, 20, 8, accent, 100);

    int eye_y = body_y + 67;
    if (pet_action_is("SLEEP")) {
        display_fill_rect(body_x + 30, eye_y + 5, 18, 3, accent);
        display_fill_rect(body_x + 72, eye_y + 5, 18, 3, accent);
    } else {
        int eye_shift = pet_action_is("THINK") ? (int)(s_pet_phase % 4U) - 2 : 0;
        display_fill_rect(body_x + 34 + eye_shift, eye_y, 10, 14, theme.text);
        display_fill_rect(body_x + 76 + eye_shift, eye_y, 10, 14, theme.text);
    }
    if (pet_action_is("TALK") && (s_pet_phase & 1U))
        display_fill_rect(body_x + 50, body_y + 96, 20, 14, accent);
    else
        display_fill_rect(body_x + 50, body_y + 100, 20, 4, accent);

    if (pet_action_is("SCAN")) {
        int scan_y = body_y + 34 + (int)(s_pet_phase % 74U);
        display_fill_rect_alpha(body_x + 12, scan_y, 96, 2, theme.secondary, 90);
    }
    if (pet_action_is("CELEBRATE")) {
        display_fill_rect(24, 74 + (s_pet_phase % 18U), 8, 8, theme.secondary);
        display_fill_rect(206, 98 - (s_pet_phase % 18U), 8, 8, accent);
        display_fill_rect(34, 174 - (s_pet_phase % 12U), 5, 5, accent);
        display_fill_rect(198, 166 + (s_pet_phase % 12U), 5, 5, theme.secondary);
    }
    display_render_pet_bubble(theme);
}

static void display_render_settings(void)
{
    visual_palette_t theme = visual_palette();
    display_prepare_background(theme.base);
    display_fill_rect_alpha(0, 0, TFT_WIDTH, 84, theme.panel, s_panel_opacity);
    display_fill_rect_alpha(12, 96, 216, 64, theme.panel, s_panel_opacity);
    display_fill_rect_alpha(12, 176, 216, 112, theme.panel, s_panel_opacity);
    display_fill_rect_alpha(0, 0, TFT_WIDTH, 8, theme.accent, s_hud_opacity);
    display_text(18, 24, "SYSTEM DECK", 3, theme.text);
    display_text(18, 58, "DISPLAY ROUTER", 2, theme.muted);
    display_fill_rect_alpha(18, 76, 204, 3, theme.accent, s_hud_opacity);
    display_text(28, 112, "DEVELOPER", 3, theme.accent);
    display_text(20, 190, "OK  OPEN PANEL", 2, theme.text);
    display_text(20, 224, "BACK  RETURN", 2, theme.muted);
    display_text(20, 268, "STYLE LINKED", 2, theme.secondary);
}

static void display_render_developer(uint8_t page)
{
    visual_palette_t theme = visual_palette();
    uint16_t white = theme.text;
    uint16_t cyan = theme.accent;
    uint16_t green = rgb565(80, 255, 145);
    uint16_t amber = rgb565(255, 185, 70);
    uint16_t red = rgb565(255, 80, 80);
    uint16_t muted = theme.muted;
    char line[32];

    display_prepare_background(theme.base);
    display_fill_rect_alpha(0, 0, TFT_WIDTH, TFT_HEIGHT, theme.panel,
                            s_panel_opacity > 85 ? s_panel_opacity : 85);
    display_fill_rect_alpha(0, 0, TFT_WIDTH, 8, cyan, s_hud_opacity);
    display_text(14, 20, "DEVELOPER", 3, white);
    snprintf(line, sizeof(line), "PAGE %u OF 4", (unsigned)(page + 1));
    display_text(16, 56, line, 2, muted);
    display_fill_rect_alpha(14, 82, 212, 2, cyan, s_hud_opacity);

    if (page == 0) {
        display_text(16, 102, "TFT SPI TX ONLY", 2, cyan);
        display_text(16, 134, "NO MISO READBACK", 2, amber);
        display_text(16, 166, s_backlight_commanded_on ? "BL CMD ON" : "BL CMD OFF", 2,
                     s_backlight_commanded_on ? green : red);
        display_text(16, 198, "PHYSICAL UNKNOWN", 2, amber);
        display_text(16, 230, s_mpu_ready ? "MPU I2C OK" : "MPU I2C MISSING", 2,
                     s_mpu_ready ? green : red);
        display_text(16, 262, "IF BLACK CHECK", 2, white);
        display_text(16, 292, "POWER GND BL", 2, amber);
    } else if (page == 1) {
        display_text(16, 100, "TFT WIRING", 2, cyan);
        display_text(16, 134, "SCK 12  MOSI 11", 2, white);
        display_text(16, 166, "CS 10   DC 7", 2, white);
        display_text(16, 198, "RST 6   BL 5", 2, white);
        display_text(16, 238, "VCC 3V3", 2, amber);
        display_text(16, 270, "GND COMMON", 2, amber);
    } else if (page == 2) {
        display_text(16, 98, "BUTTON LEVELS", 2, cyan);
        snprintf(line, sizeof(line), "UP %d  DOWN %d",
                 gpio_get_level(PIN_BUTTON_UP), gpio_get_level(PIN_BUTTON_DOWN));
        display_text(16, 132, line, 2, white);
        snprintf(line, sizeof(line), "LEFT %d RIGHT %d",
                 gpio_get_level(PIN_BUTTON_LEFT), gpio_get_level(PIN_BUTTON_RIGHT));
        display_text(16, 166, line, 2, white);
        snprintf(line, sizeof(line), "OK %d  BACK %d",
                 gpio_get_level(PIN_BUTTON_OK), gpio_get_level(PIN_BUTTON_BACK));
        display_text(16, 200, line, 2, white);
        display_text(16, 246, "RELEASED HIGH", 2, green);
        display_text(16, 276, "PRESSED LOW", 2, amber);
    } else {
        display_text(16, 100, "COLOR TEST", 3, cyan);
        display_text(16, 154, "PRESS OK", 2, white);
        display_text(16, 188, "RGB WHITE BLACK", 2, muted);
        display_text(16, 246, "NO COLOR CHECK", 2, white);
        display_text(16, 276, "SCK MOSI CS DC", 2, amber);
    }

    display_text(16, 306, "LEFT RIGHT  BACK", 1, muted);
}

static void display_render_color_test(void)
{
    display_fill_rect(0, 0, 80, 160, rgb565(255, 0, 0));
    display_fill_rect(80, 0, 80, 160, rgb565(0, 255, 0));
    display_fill_rect(160, 0, 80, 160, rgb565(0, 0, 255));
    display_fill_rect(0, 160, 80, 160, rgb565(255, 255, 255));
    display_fill_rect(80, 160, 80, 160, rgb565(120, 120, 120));
    display_fill_rect(160, 160, 80, 160, rgb565(0, 0, 0));
}

static void display_render_current(void)
{
    if (!s_display_ready) {
        return;
    }
    if (s_display_mutex) xSemaphoreTake(s_display_mutex, portMAX_DELAY);
    switch (s_display_view) {
        case DISPLAY_VIEW_SETTINGS:
            display_render_settings();
            break;
        case DISPLAY_VIEW_DEVELOPER:
            display_render_developer(s_developer_page);
            break;
        case DISPLAY_VIEW_COLOR_TEST:
            display_render_color_test();
            break;
        case DISPLAY_VIEW_WALLPAPER:
            display_render_state(get_state());
            break;
        case DISPLAY_VIEW_MEDIA:
            s_live_background_override = s_media_canvas;
            display_render_state(get_state());
            s_live_background_override = NULL;
            break;
        case DISPLAY_VIEW_IDLE:
            display_render_idle();
            break;
        case DISPLAY_VIEW_PET:
            display_render_pet();
            break;
        case DISPLAY_VIEW_STATUS:
        default:
            display_render_state(get_state());
            break;
    }
    display_present();
    if (s_display_mutex) xSemaphoreGive(s_display_mutex);
}

static esp_err_t buttons_init(void)
{
    const uint64_t button_mask = (1ULL << PIN_BUTTON_UP) |
                                 (1ULL << PIN_BUTTON_DOWN) |
                                 (1ULL << PIN_BUTTON_LEFT) |
                                 (1ULL << PIN_BUTTON_RIGHT) |
                                 (1ULL << PIN_BUTTON_OK) |
                                 (1ULL << PIN_BUTTON_BACK);
    gpio_config_t button_config = {
        .pin_bit_mask = button_mask,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    ESP_RETURN_ON_ERROR(gpio_config(&button_config), TAG, "Button config failed");

    gpio_config_t interrupt_config = {
        .pin_bit_mask = 1ULL << PIN_MPU_INT,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    return gpio_config(&interrupt_config);
}

static void emit_status(void)
{
    serial_emit("STATUS,%s,MPU=%s,MOCK=%s,SAMPLES=%lu,RATE=%lu,DURATION=%lu",
                state_name(get_state()), s_mpu_ready ? "OK" : "MISSING",
                s_mock_enabled ? "ON" : "OFF", (unsigned long)s_sample_count,
                (unsigned long)s_sample_rate_hz, (unsigned long)s_duration_seconds);
}

const char *labcapsule_device_id(void)
{
    if (!s_device_id[0]) {
        uint8_t mac[6] = {0};
        if (esp_read_mac(mac, ESP_MAC_WIFI_STA) == ESP_OK) {
            snprintf(s_device_id, sizeof(s_device_id), "lc-%02x%02x%02x%02x%02x%02x",
                     mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
        } else {
            strlcpy(s_device_id, "lc-000000000000", sizeof(s_device_id));
        }
    }
    return s_device_id;
}

esp_err_t labcapsule_set_character_identity(const char *character_id, bool proxy_enabled)
{
    if (!character_id || !character_id[0] || strlen(character_id) >=
            sizeof(((labcapsule_config_t *)0)->character_id)) return ESP_ERR_INVALID_ARG;
    for (const char *point = character_id; *point; ++point) {
        if (!(isalnum((unsigned char)*point) || *point == '-' || *point == '_' || *point == '.'))
            return ESP_ERR_INVALID_ARG;
    }
    labcapsule_config_t config = *device_config_get();
    strlcpy(config.character_id, character_id, sizeof(config.character_id));
    config.pet_proxy_enabled = proxy_enabled;
    esp_err_t result = device_config_save(&config);
    if (result == ESP_OK && proxy_enabled && media_store_clip_available() &&
        get_state() != STATE_RECORDING) {
        s_idle_mode = true;
        s_display_view = DISPLAY_VIEW_PET;
        display_request_refresh();
    }
    return result;
}

esp_err_t labcapsule_set_pet_bubble(const uint8_t *payload, size_t payload_size)
{
    if (!payload || payload_size != PET_BUBBLE_BYTES ||
        get_state() == STATE_RECORDING) return ESP_ERR_INVALID_ARG;
    memcpy(s_pet_bubble, payload, PET_BUBBLE_BYTES);
    s_pet_bubble_valid = true;
    s_idle_mode = true;
    s_display_view = DISPLAY_VIEW_PET;
    display_request_refresh();
    return ESP_OK;
}

static esp_err_t start_recording(uint32_t rate_hz, uint32_t duration_seconds)
{
    if (rate_hz < MIN_SAMPLE_RATE_HZ || rate_hz > MAX_SAMPLE_RATE_HZ ||
        duration_seconds == 0 || duration_seconds > MAX_DURATION_SECONDS) {
        serial_emit("ERR,INVALID_ARGUMENT,RATE=%lu,DURATION=%lu",
                    (unsigned long)rate_hz, (unsigned long)duration_seconds);
        return ESP_ERR_INVALID_ARG;
    }
    if (!s_mpu_ready && !s_mock_enabled) {
        serial_emit("ERR,MPU_NOT_FOUND,USE_MOCK_ON_OR_CHECK_WIRING");
        return ESP_ERR_NOT_FOUND;
    }
    if (get_state() == STATE_RECORDING) {
        serial_emit("ERR,ALREADY_RECORDING");
        return ESP_ERR_INVALID_STATE;
    }
    if (s_mpu_ready && mpu_set_sample_rate(rate_hz) != ESP_OK) {
        serial_emit("ERR,MPU_CONFIG_FAILED");
        set_state(STATE_ERROR);
        return ESP_FAIL;
    }

    /* Open the offline session before exposing RECORDING to the sampler task.
     * Otherwise the first one or two samples can race ahead of file creation. */
    esp_err_t storage_result = offline_store_start(rate_hz, duration_seconds);
    if (storage_result != ESP_OK)
        serial_emit("WARN,OFFLINE_STORAGE_UNAVAILABLE,%s",
                    esp_err_to_name(storage_result));

    s_idle_mode = false;
    s_display_view = DISPLAY_VIEW_STATUS;
    portENTER_CRITICAL(&s_state_lock);
    s_sample_rate_hz = rate_hz;
    s_duration_seconds = duration_seconds;
    s_sample_count = 0;
    s_recording_started_us = esp_timer_get_time();
    s_state = STATE_RECORDING;
    portEXIT_CRITICAL(&s_state_lock);
    sensor_hub_set_scan_enabled(false);
    s_display_view = DISPLAY_VIEW_STATUS;
    display_request_refresh();
    serial_emit("OK,START,RATE=%lu,DURATION=%lu,SOURCE=%s",
                (unsigned long)rate_hz, (unsigned long)duration_seconds,
                s_mock_enabled ? "MOCK" : "MPU6050");
    serial_emit("HEADER,timestamp_us,ax_g,ay_g,az_g,gx_dps,gy_dps,gz_dps");
    return ESP_OK;
}

static void stop_recording(bool aborted)
{
    if (get_state() != STATE_RECORDING) {
        serial_emit("ERR,NOT_RECORDING");
        return;
    }
    set_state(aborted ? STATE_ABORTED : STATE_COMPLETE);
    esp_err_t storage_result = offline_store_finish(aborted);
    if (storage_result != ESP_OK && storage_result != ESP_ERR_INVALID_STATE)
        serial_emit("WARN,OFFLINE_FINALIZE_FAILED,%s", esp_err_to_name(storage_result));
    serial_emit("OK,%s,SAMPLES=%lu", aborted ? "ABORT" : "STOP",
                (unsigned long)s_sample_count);
}

static void emit_display_diagnostics(void)
{
    serial_emit("DISPLAY,DRIVER=%s,BUS=SPI_TX_ONLY,READBACK=UNAVAILABLE,BL_CMD=%s,INVERT=%s",
                s_display_ready ? "READY" : "FAILED", s_backlight_commanded_on ? "ON" : "OFF",
                s_display_inverted ? "ON" : "OFF");
    serial_emit("DISPLAY,WIRING,SCK=12,MOSI=11,CS=10,DC=7,RST=6,BL=5,VCC=3V3,GND=COMMON");
    serial_emit("DISPLAY,DIAG,NO_BACKLIGHT=CHECK_POWER_GND_BL,WHITE_SCREEN=CHECK_SCK_MOSI_CS_DC_RST");
}

static void handle_display_command(char **save_pointer)
{
    char *action = strtok_r(NULL, ", ", save_pointer);
    if (!action) {
        emit_display_diagnostics();
        return;
    }
    for (char *p = action; *p; ++p) {
        *p = (char)toupper((unsigned char)*p);
    }

    if (strcmp(action, "DEV") == 0 || strcmp(action, "DEVELOPER") == 0) {
        s_display_view = DISPLAY_VIEW_DEVELOPER;
        s_developer_page = 0;
        display_request_refresh();
        serial_emit("OK,DISPLAY,DEVELOPER");
        emit_display_diagnostics();
    } else if (strcmp(action, "TEST") == 0 || strcmp(action, "COLOR") == 0) {
        s_display_view = DISPLAY_VIEW_COLOR_TEST;
        display_request_refresh();
        serial_emit("OK,DISPLAY,COLOR_TEST");
    } else if (strcmp(action, "WALLPAPER") == 0) {
        if (!wallpaper_available()) {
            serial_emit("ERR,WALLPAPER_NOT_FOUND");
            return;
        }
        s_display_view = DISPLAY_VIEW_WALLPAPER;
        display_request_refresh();
        serial_emit("OK,DISPLAY,WALLPAPER");
    } else if (strcmp(action, "SETTINGS") == 0) {
        s_display_view = DISPLAY_VIEW_SETTINGS;
        display_request_refresh();
        serial_emit("OK,DISPLAY,SETTINGS");
    } else if (strcmp(action, "PET") == 0) {
        if (get_state() == STATE_RECORDING) {
            serial_emit("ERR,DISPLAY,PET,RECORDING_ACTIVE");
            return;
        }
        s_idle_mode = true;
        s_display_view = DISPLAY_VIEW_PET;
        display_request_refresh();
        serial_emit("OK,DISPLAY,PET");
    } else if (strcmp(action, "HOME") == 0 || strcmp(action, "STATUS") == 0) {
        s_idle_mode = false;
        s_display_view = DISPLAY_VIEW_STATUS;
        display_request_refresh();
        serial_emit("OK,DISPLAY,HOME");
    } else if (strcmp(action, "INVERT") == 0) {
        s_display_inverted = !s_display_inverted;
        if (s_display_ready) {
            esp_lcd_panel_invert_color(s_panel, s_display_inverted);
        }
        display_request_refresh();
        serial_emit("OK,DISPLAY,INVERT=%s", s_display_inverted ? "ON" : "OFF");
    } else if (strcmp(action, "BL") == 0 || strcmp(action, "BACKLIGHT") == 0) {
        char *mode = strtok_r(NULL, ", ", save_pointer);
        if (!mode) {
            serial_emit("DISPLAY,BL_CMD=%s", s_backlight_commanded_on ? "ON" : "OFF");
            return;
        }
        for (char *p = mode; *p; ++p) {
            *p = (char)toupper((unsigned char)*p);
        }
        bool enabled = strcmp(mode, "ON") == 0 || strcmp(mode, "1") == 0;
        display_set_backlight(enabled);
        serial_emit("OK,DISPLAY,BL_CMD=%s", enabled ? "ON" : "OFF");
    } else {
        serial_emit("ERR,UNKNOWN_DISPLAY_ACTION,%s", action);
    }
}

static uint32_t crc32_update(uint32_t crc, const uint8_t *data, size_t length)
{
    for (size_t index = 0; index < length; ++index) {
        crc ^= data[index];
        for (uint8_t bit = 0; bit < 8; ++bit) {
            crc = (crc >> 1) ^ (0xEDB88320U & (uint32_t)-(int32_t)(crc & 1U));
        }
    }
    return crc;
}

static void serial_upload_abort(void)
{
    if (s_serial_upload_kind == SERIAL_UPLOAD_WALLPAPER) wallpaper_upload_abort();
    else if (s_serial_upload_kind == SERIAL_UPLOAD_CLIP) media_store_upload_abort();
    s_serial_upload_kind = SERIAL_UPLOAD_NONE;
    s_serial_upload_expected = 0;
    s_serial_upload_received = 0;
    s_serial_upload_last_byte_us = 0;
}

static esp_err_t serial_upload_begin(serial_source_t source, const char *kind_text,
                                     size_t expected, uint32_t expected_crc)
{
    if (s_serial_upload_kind != SERIAL_UPLOAD_NONE) return ESP_ERR_INVALID_STATE;
    serial_upload_kind_t kind = SERIAL_UPLOAD_NONE;
    if (strcmp(kind_text, "WALLPAPER") == 0 && expected == WALLPAPER_PAYLOAD_BYTES)
        kind = SERIAL_UPLOAD_WALLPAPER;
    else if (strcmp(kind_text, "CLIP") == 0 && expected >= 29 &&
             expected <= MEDIA_STORE_MAX_CLIP_BYTES)
        kind = SERIAL_UPLOAD_CLIP;
    else if (strcmp(kind_text, "PETBUBBLE") == 0 && expected == PET_BUBBLE_BYTES)
        kind = SERIAL_UPLOAD_PET_BUBBLE;
    else return ESP_ERR_INVALID_SIZE;

    esp_err_t result = ESP_OK;
    if (kind != SERIAL_UPLOAD_PET_BUBBLE) {
        labcapsule_media_clip_stop();
        /* Let the playback task close the old current.lcg before atomic replacement. */
        vTaskDelay(pdMS_TO_TICKS(60));
        result = kind == SERIAL_UPLOAD_WALLPAPER
                ? wallpaper_upload_begin(expected) : media_store_upload_begin(expected);
    }
    if (result != ESP_OK) return result;
    s_serial_upload_source = source;
    s_serial_upload_expected = expected;
    s_serial_upload_received = 0;
    s_serial_upload_expected_crc = expected_crc;
    s_serial_upload_crc = 0xFFFFFFFFU;
    s_serial_upload_last_byte_us = esp_timer_get_time();
    s_serial_upload_kind = kind;
    serial_emit("READY,UPLOAD,%s,BYTES=%u", kind_text, (unsigned)expected);
    return ESP_OK;
}

static void serial_upload_finish(void)
{
    serial_upload_kind_t kind = s_serial_upload_kind;
    uint32_t actual_crc = s_serial_upload_crc ^ 0xFFFFFFFFU;
    uint32_t expected_crc = s_serial_upload_expected_crc;
    esp_err_t result = ESP_OK;
    if (actual_crc != s_serial_upload_expected_crc) {
        result = ESP_ERR_INVALID_CRC;
    } else if (kind == SERIAL_UPLOAD_WALLPAPER) {
        result = wallpaper_upload_finish();
    } else if (kind == SERIAL_UPLOAD_CLIP) {
        result = media_store_upload_finish();
    } else if (kind == SERIAL_UPLOAD_PET_BUBBLE) {
        memcpy(s_pet_bubble, s_media_receive_buffer, PET_BUBBLE_BYTES);
        s_pet_bubble_valid = true;
    }
    if (result != ESP_OK) {
        serial_upload_abort();
        serial_emit("ERR,UPLOAD,%s,ACTUAL=%08lX,EXPECTED=%08lX,REASON=%s",
                    kind == SERIAL_UPLOAD_CLIP ? "CLIP" :
                            (kind == SERIAL_UPLOAD_PET_BUBBLE ? "PETBUBBLE" : "WALLPAPER"),
                    (unsigned long)actual_crc, (unsigned long)expected_crc,
                    esp_err_to_name(result));
        return;
    }
    s_serial_upload_kind = SERIAL_UPLOAD_NONE;
    s_serial_upload_expected = 0;
    s_serial_upload_received = 0;
    if (kind == SERIAL_UPLOAD_WALLPAPER) {
        media_store_delete_clip();
        s_display_view = DISPLAY_VIEW_WALLPAPER;
        display_request_refresh();
        serial_emit("OK,UPLOAD,WALLPAPER,CRC=%08lX", (unsigned long)actual_crc);
    } else if (kind == SERIAL_UPLOAD_CLIP) {
        wallpaper_clear();
        serial_emit("OK,UPLOAD,CLIP,CRC=%08lX", (unsigned long)actual_crc);
        labcapsule_media_clip_start();
    } else {
        s_idle_mode = true;
        s_display_view = DISPLAY_VIEW_PET;
        display_request_refresh();
        serial_emit("OK,UPLOAD,PETBUBBLE,CRC=%08lX", (unsigned long)actual_crc);
    }
}

static size_t serial_upload_write(serial_source_t source, const uint8_t *data, size_t length)
{
    if (s_serial_upload_kind == SERIAL_UPLOAD_NONE || source != s_serial_upload_source)
        return 0;
    size_t remaining = s_serial_upload_expected - s_serial_upload_received;
    size_t consumed = length < remaining ? length : remaining;
    esp_err_t result;
    if (s_serial_upload_kind == SERIAL_UPLOAD_WALLPAPER)
        result = wallpaper_upload_write(data, consumed);
    else if (s_serial_upload_kind == SERIAL_UPLOAD_CLIP)
        result = media_store_upload_write(data, consumed);
    else {
        memcpy(s_media_receive_buffer + s_serial_upload_received, data, consumed);
        result = ESP_OK;
    }
    if (result != ESP_OK) {
        serial_emit("ERR,UPLOAD,WRITE,%s", esp_err_to_name(result));
        serial_upload_abort();
        return consumed;
    }
    s_serial_upload_crc = crc32_update(s_serial_upload_crc, data, consumed);
    s_serial_upload_received += consumed;
    s_serial_upload_last_byte_us = esp_timer_get_time();
    if (s_serial_upload_received == s_serial_upload_expected) serial_upload_finish();
    return consumed;
}

static void handle_command(char *line, serial_source_t source)
{
    while (*line && isspace((unsigned char)*line)) {
        ++line;
    }
    char *end = line + strlen(line);
    while (end > line && isspace((unsigned char)end[-1])) {
        *--end = '\0';
    }
    if (*line == '\0') {
        return;
    }

    char *save_pointer = NULL;
    char *command = strtok_r(line, ", ", &save_pointer);
    for (char *p = command; *p; ++p) {
        *p = (char)toupper((unsigned char)*p);
    }

    if (strcmp(command, "PING") == 0) {
        serial_emit("PONG,LABCAPSULE,%s,DEVICE=%s", LABCAPSULE_VERSION,
                    labcapsule_device_id());
    } else if (strcmp(command, "IDENTITY") == 0) {
        const labcapsule_config_t *config = device_config_get();
        serial_emit("IDENTITY,DEVICE=%s,ALIAS=%s,CHARACTER=%s,PROXY=%s,CAPABILITIES=USB|WIFI|BLE|MQTT|DISPLAY|MEDIA|OFFLINE|I2C|INPUT|MIC_PORT",
                    labcapsule_device_id(), config->device_alias, config->character_id,
                    config->pet_proxy_enabled ? "ON" : "OFF");
    } else if (strcmp(command, "STATUS") == 0) {
        /* Some MPU6050 breakout boards need longer than the main boot retry
         * window before their I2C identity/configuration reads stabilize.
         * STATUS is part of every desktop/mobile handshake, so use it as a
         * transparent recovery point instead of requiring the user to open
         * the diagnostic page and issue SENSORS manually. */
        if (!s_mpu_ready) {
            esp_err_t recovery_result = mpu_probe_and_configure();
            sensor_hub_set_primary_ready("mpu6050", s_mpu_ready);
            if (recovery_result == ESP_OK) {
                ESP_LOGI(TAG, "MPU6050 recovered during STATUS handshake");
                display_request_refresh();
            }
        }
        emit_status();
    } else if (strcmp(command, "NETWORK") == 0) {
        char network[384];
        connectivity_build_status_json(network, sizeof(network));
        serial_emit("NETWORK,%s", network);
    } else if (strcmp(command, "DISPLAY") == 0 || strcmp(command, "TFT") == 0) {
        handle_display_command(&save_pointer);
    } else if (strcmp(command, "STYLE") == 0) {
        char *preset_text = strtok_r(NULL, ", ", &save_pointer);
        char *wallpaper_text = strtok_r(NULL, ", ", &save_pointer);
        char *panel_text = strtok_r(NULL, ", ", &save_pointer);
        char *hud_text = strtok_r(NULL, ", ", &save_pointer);
        unsigned preset = preset_text ? strtoul(preset_text, NULL, 10) : 0;
        unsigned wallpaper_opacity = wallpaper_text ? strtoul(wallpaper_text, NULL, 10) : 0;
        unsigned panel_opacity = panel_text ? strtoul(panel_text, NULL, 10) : 0;
        unsigned hud_opacity = hud_text ? strtoul(hud_text, NULL, 10) : 0;
        if (!preset_text || !wallpaper_text || !panel_text || !hud_text || preset > 2 ||
            wallpaper_opacity > 100 || panel_opacity > 100 || hud_opacity > 100 ||
            labcapsule_set_visual_style((uint8_t)preset, (uint8_t)wallpaper_opacity,
                                        (uint8_t)panel_opacity,
                                        (uint8_t)hud_opacity) != ESP_OK) {
            serial_emit("ERR,STYLE,EXPECTED=STYLE,PRESET,WALL,PANEL,HUD");
        } else {
            serial_emit("OK,STYLE,%u,%u,%u,%u", preset, wallpaper_opacity,
                        panel_opacity, hud_opacity);
        }
    } else if (strcmp(command, "DEVELOPER") == 0 || strcmp(command, "DEV") == 0) {
        s_display_view = DISPLAY_VIEW_DEVELOPER;
        s_developer_page = 0;
        display_request_refresh();
        serial_emit("OK,DISPLAY,DEVELOPER");
        emit_display_diagnostics();
    } else if (strcmp(command, "MODE") == 0) {
        char *mode = strtok_r(NULL, ", ", &save_pointer);
        if (mode) for (char *p = mode; *p; ++p)
            *p = (char)toupper((unsigned char)*p);
        if (!mode || (strcmp(mode, "IDLE") != 0 && strcmp(mode, "EXPERIMENT") != 0)) {
            serial_emit("ERR,MODE,EXPECTED=IDLE|EXPERIMENT");
        } else if (labcapsule_set_idle_mode(strcmp(mode, "IDLE") == 0) != ESP_OK) {
            serial_emit("ERR,MODE,RECORDING_ACTIVE");
        }
    } else if (strcmp(command, "NOTICE") == 0) {
        char *title = strtok_r(NULL, ",", &save_pointer);
        char *message = strtok_r(NULL, ",", &save_pointer);
        labcapsule_set_idle_notice(title, message);
    } else if (strcmp(command, "HOST") == 0) {
        char *cpu_text = strtok_r(NULL, ", ", &save_pointer);
        char *ram_text = strtok_r(NULL, ", ", &save_pointer);
        char *disk_text = strtok_r(NULL, ", ", &save_pointer);
        char *temp_text = strtok_r(NULL, ", ", &save_pointer);
        unsigned cpu = cpu_text ? strtoul(cpu_text, NULL, 10) : 101;
        unsigned ram = ram_text ? strtoul(ram_text, NULL, 10) : 101;
        unsigned disk = disk_text ? strtoul(disk_text, NULL, 10) : 101;
        long temperature = temp_text ? strtol(temp_text, NULL, 10) : -1;
        if (cpu > 100 || ram > 100 || disk > 100 || temperature < -1 ||
            temperature > 150) {
            serial_emit("ERR,HOST,EXPECTED=CPU,RAM,DISK,TEMP");
        } else {
            s_host_cpu_percent = (uint8_t)cpu;
            s_host_ram_percent = (uint8_t)ram;
            s_host_disk_percent = (uint8_t)disk;
            s_host_temperature_c = (int16_t)temperature;
            s_host_last_heartbeat_us = esp_timer_get_time();
            s_host_link_active = true;
            if (get_state() != STATE_RECORDING && s_display_view != DISPLAY_VIEW_PET) {
                s_idle_mode = true;
                s_display_view = DISPLAY_VIEW_IDLE;
            }
            display_request_refresh();
            serial_emit("OK,HOST,CPU=%u,RAM=%u,DISK=%u,TEMP=%ld",
                        cpu, ram, disk, temperature);
        }
    } else if (strcmp(command, "PET") == 0) {
        char *action = strtok_r(NULL, ", ", &save_pointer);
        if (action) for (char *p = action; *p; ++p)
            *p = (char)toupper((unsigned char)*p);
        if (!action || strcmp(action, "STATUS") == 0) {
            const labcapsule_config_t *config = device_config_get();
            serial_emit("PET,VIEW=%s,EMOTION=%s,ACTION=%s,BUBBLE=%s,CHARACTER=%s,PROXY=%s",
                        s_display_view == DISPLAY_VIEW_PET ? "ON" : "OFF",
                        s_pet_emotion, s_pet_action, s_pet_bubble_valid ? "YES" : "NO",
                        config->character_id, config->pet_proxy_enabled ? "ON" : "OFF");
        } else if (strcmp(action, "SHOW") == 0) {
            if (get_state() == STATE_RECORDING) serial_emit("ERR,PET,RECORDING_ACTIVE");
            else {
                s_idle_mode = true;
                s_display_view = DISPLAY_VIEW_PET;
                display_request_refresh();
                serial_emit("OK,PET,SHOW");
            }
        } else if (strcmp(action, "HIDE") == 0) {
            s_idle_mode = false;
            s_display_view = DISPLAY_VIEW_STATUS;
            display_request_refresh();
            serial_emit("OK,PET,HIDE");
        } else if (strcmp(action, "CLEAR") == 0) {
            memset(s_pet_bubble, 0, sizeof(s_pet_bubble));
            s_pet_bubble_valid = false;
            display_request_refresh();
            serial_emit("OK,PET,CLEAR");
        } else if (strcmp(action, "STATE") == 0) {
            char *emotion = strtok_r(NULL, ", ", &save_pointer);
            char *motion = strtok_r(NULL, ", ", &save_pointer);
            if (!emotion || !motion || strlen(emotion) >= sizeof(s_pet_emotion) ||
                strlen(motion) >= sizeof(s_pet_action) || get_state() == STATE_RECORDING) {
                serial_emit("ERR,PET,EXPECTED=PET,STATE,EMOTION,ACTION");
            } else {
                for (char *p = emotion; *p; ++p) *p = (char)toupper((unsigned char)*p);
                for (char *p = motion; *p; ++p) *p = (char)toupper((unsigned char)*p);
                snprintf(s_pet_emotion, sizeof(s_pet_emotion), "%s", emotion);
                snprintf(s_pet_action, sizeof(s_pet_action), "%s", motion);
                s_pet_phase = 0;
                s_idle_mode = true;
                s_display_view = DISPLAY_VIEW_PET;
                display_request_refresh();
                serial_emit("OK,PET,STATE,%s,%s", s_pet_emotion, s_pet_action);
            }
        } else if (strcmp(action, "IDENTITY") == 0) {
            char *character_id = strtok_r(NULL, ", ", &save_pointer);
            char *proxy = strtok_r(NULL, ", ", &save_pointer);
            bool proxy_enabled = proxy && strcmp(proxy, "PROXY") == 0;
            esp_err_t result = labcapsule_set_character_identity(character_id, proxy_enabled);
            serial_emit(result == ESP_OK ? "OK,PET,IDENTITY,%s,%s" :
                        "ERR,PET,IDENTITY,%s,%s", character_id ? character_id : "",
                        proxy_enabled ? "PROXY" : "NO_PROXY");
        } else {
            serial_emit("ERR,PET,EXPECTED=SHOW|HIDE|CLEAR|STATE|IDENTITY|STATUS");
        }
    } else if (strcmp(command, "GIF") == 0) {
        char *action = strtok_r(NULL, ", ", &save_pointer);
        if (action) for (char *p = action; *p; ++p)
            *p = (char)toupper((unsigned char)*p);
        if (action && strcmp(action, "PLAY") == 0) {
            if (labcapsule_media_clip_start() != ESP_OK) serial_emit("ERR,GIF,NOT_FOUND");
        } else if (action && strcmp(action, "STOP") == 0) {
            labcapsule_media_clip_stop();
        } else if (action && strcmp(action, "DELETE") == 0) {
            labcapsule_media_clip_stop();
            esp_err_t result = media_store_delete_clip();
            serial_emit(result == ESP_OK ? "OK,GIF,DELETE" : "ERR,GIF,DELETE");
        } else if (action && strcmp(action, "FPS") == 0) {
            char *fps_text = strtok_r(NULL, ", ", &save_pointer);
            unsigned fps = fps_text ? strtoul(fps_text, NULL, 10) : 0;
            if (labcapsule_media_clip_set_fps((uint8_t)fps) != ESP_OK)
                serial_emit("ERR,GIF,FPS_RANGE=1-%u", LABCAPSULE_MEDIA_MAX_FPS);
        } else {
            serial_emit("GIF,STORED=%s,PLAYING=%s,FPS=%u,BYTES=%u",
                        media_store_clip_available() ? "YES" : "NO",
                        s_media_clip_playing ? "YES" : "NO",
                        (unsigned)s_media_clip_fps,
                        (unsigned)media_store_clip_size());
        }
    } else if (strcmp(command, "UPLOAD") == 0) {
        char *kind = strtok_r(NULL, ", ", &save_pointer);
        char *size_text = strtok_r(NULL, ", ", &save_pointer);
        char *crc_text = strtok_r(NULL, ", ", &save_pointer);
        if (kind) for (char *p = kind; *p; ++p) *p = (char)toupper((unsigned char)*p);
        size_t size = size_text ? (size_t)strtoul(size_text, NULL, 10) : 0;
        uint32_t crc = crc_text ? (uint32_t)strtoul(crc_text, NULL, 16) : 0;
        esp_err_t result = kind && size_text && crc_text
                ? serial_upload_begin(source, kind, size, crc) : ESP_ERR_INVALID_ARG;
        if (result != ESP_OK)
            serial_emit("ERR,UPLOAD,EXPECTED=UPLOAD,CLIP|WALLPAPER,SIZE,CRC32,%s",
                        esp_err_to_name(result));
    } else if (strcmp(command, "SENSORS") == 0 || strcmp(command, "SCAN") == 0) {
        esp_err_t result = s_mpu_ready ? ESP_OK : mpu_probe_and_configure();
        size_t found = sensor_hub_discover();
        sensor_hub_set_primary_ready("mpu6050", s_mpu_ready);
        display_request_refresh();
        serial_emit("SENSORS,COUNT=%u,MPU=%s,ADDRESS=0x%02X,RESULT=%s",
                    (unsigned)found, s_mpu_ready ? "OK" : "MISSING", s_mpu_address,
                    esp_err_to_name(result));
    } else if (strcmp(command, "START") == 0) {
        char *rate_text = strtok_r(NULL, ", ", &save_pointer);
        char *duration_text = strtok_r(NULL, ", ", &save_pointer);
        uint32_t rate = rate_text ? (uint32_t)strtoul(rate_text, NULL, 10) : s_sample_rate_hz;
        uint32_t duration = duration_text ? (uint32_t)strtoul(duration_text, NULL, 10)
                                          : s_duration_seconds;
        start_recording(rate, duration);
    } else if (strcmp(command, "STOP") == 0) {
        stop_recording(false);
    } else if (strcmp(command, "ABORT") == 0) {
        stop_recording(true);
    } else if (strcmp(command, "MOCK") == 0) {
        char *mode = strtok_r(NULL, ", ", &save_pointer);
        if (!mode) {
            serial_emit("MOCK,%s", s_mock_enabled ? "ON" : "OFF");
        } else {
            for (char *p = mode; *p; ++p) {
                *p = (char)toupper((unsigned char)*p);
            }
            if (strcmp(mode, "ON") == 0 || strcmp(mode, "1") == 0) {
                s_mock_enabled = true;
                serial_emit("OK,MOCK,ON");
            } else if (strcmp(mode, "OFF") == 0 || strcmp(mode, "0") == 0) {
                s_mock_enabled = false;
                serial_emit("OK,MOCK,OFF");
            } else {
                serial_emit("ERR,INVALID_MOCK_MODE");
            }
        }
    } else if (strcmp(command, "HELP") == 0) {
        serial_emit("COMMANDS,PING|IDENTITY|STATUS|NETWORK|START[,RATE,DURATION]|STOP|ABORT|MOCK,ON|OFF");
        serial_emit("COMMANDS,DISPLAY[,PET|DEV|TEST|WALLPAPER|SETTINGS|HOME|INVERT|BL,ON|OFF]");
        serial_emit("COMMANDS,STYLE,PRESET,WALL,PANEL,HUD");
        serial_emit("COMMANDS,MODE,IDLE|EXPERIMENT");
        serial_emit("COMMANDS,NOTICE,TITLE,MESSAGE");
        serial_emit("COMMANDS,HOST,CPU,RAM,DISK,TEMP|GIF,PLAY|STOP|DELETE|FPS,N");
        serial_emit("COMMANDS,PET,SHOW|HIDE|CLEAR|STATE,EMOTION,ACTION|IDENTITY,ID,PROXY|STATUS");
        serial_emit("COMMANDS,SENSORS|SCAN");
        serial_emit("COMMANDS,UPLOAD,CLIP|WALLPAPER|PETBUBBLE,SIZE,CRC32_THEN_BINARY");
    } else {
        serial_emit("ERR,UNKNOWN_COMMAND,%s", command);
    }
}

static void accept_serial_byte(serial_source_t source, uint8_t byte)
{
    static char uart_line[SERIAL_LINE_CAPACITY];
    static char usb_line[SERIAL_LINE_CAPACITY];
    static size_t uart_length = 0;
    static size_t usb_length = 0;
    char *line = source == SERIAL_SOURCE_UART ? uart_line : usb_line;
    size_t *length = source == SERIAL_SOURCE_UART ? &uart_length : &usb_length;

    if (byte == '\r' || byte == '\n') {
        if (*length > 0) {
            line[*length] = '\0';
            handle_command(line, source);
            *length = 0;
        }
        return;
    }
    if (byte == 0x08 || byte == 0x7F) {
        if (*length > 0) {
            --(*length);
        }
        return;
    }
    if (isprint(byte)) {
        if (*length < SERIAL_LINE_CAPACITY - 1) {
            line[(*length)++] = (char)byte;
        } else {
            *length = 0;
            serial_emit("ERR,COMMAND_TOO_LONG");
        }
    }
}

static void serial_task(void *argument)
{
    (void)argument;
    uint8_t buffer[512];
    while (true) {
        if (s_serial_upload_kind != SERIAL_UPLOAD_NONE &&
            esp_timer_get_time() - s_serial_upload_last_byte_us > 10000000LL) {
            serial_upload_kind_t timed_out_kind = s_serial_upload_kind;
            size_t timed_out_received = s_serial_upload_received;
            size_t timed_out_expected = s_serial_upload_expected;
            serial_upload_abort();
            serial_emit("ERR,UPLOAD,%s,RECEIVED=%u,EXPECTED=%u,REASON=TIMEOUT",
                        timed_out_kind == SERIAL_UPLOAD_CLIP ? "CLIP" :
                                (timed_out_kind == SERIAL_UPLOAD_PET_BUBBLE
                                 ? "PETBUBBLE" : "WALLPAPER"),
                        (unsigned)timed_out_received, (unsigned)timed_out_expected);
        }
        int uart_bytes = uart_read_bytes(UART_NUM_0, buffer, sizeof(buffer), pdMS_TO_TICKS(5));
        size_t offset = 0;
        while (offset < (size_t)uart_bytes) {
            size_t consumed = serial_upload_write(SERIAL_SOURCE_UART, buffer + offset,
                                                  (size_t)uart_bytes - offset);
            if (consumed > 0) offset += consumed;
            else accept_serial_byte(SERIAL_SOURCE_UART, buffer[offset++]);
        }
        if (s_usb_serial_ready) {
            int usb_bytes = usb_serial_jtag_read_bytes(buffer, sizeof(buffer), 0);
            offset = 0;
            while (offset < (size_t)usb_bytes) {
                size_t consumed = serial_upload_write(SERIAL_SOURCE_USB, buffer + offset,
                                                      (size_t)usb_bytes - offset);
                if (consumed > 0) offset += consumed;
                else accept_serial_byte(SERIAL_SOURCE_USB, buffer[offset++]);
            }
        }
    }
}

static void sampling_task(void *argument)
{
    (void)argument;
    TickType_t last_wake = xTaskGetTickCount();
    device_state_t prior_state = STATE_BOOT;
    unsigned consecutive_read_failures = 0;

    while (true) {
        device_state_t state = get_state();
        if (state != STATE_RECORDING) {
            prior_state = state;
            consecutive_read_failures = 0;
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }
        if (prior_state != STATE_RECORDING) {
            last_wake = xTaskGetTickCount();
            prior_state = STATE_RECORDING;
        }

        int64_t elapsed_us = esp_timer_get_time() - s_recording_started_us;
        if (elapsed_us >= (int64_t)s_duration_seconds * 1000000LL) {
            set_state(STATE_COMPLETE);
            esp_err_t storage_result = offline_store_finish(false);
            if (storage_result != ESP_OK && storage_result != ESP_ERR_INVALID_STATE)
                serial_emit("WARN,OFFLINE_FINALIZE_FAILED,%s",
                            esp_err_to_name(storage_result));
            serial_emit("OK,COMPLETE,SAMPLES=%lu", (unsigned long)s_sample_count);
            continue;
        }

        motion_sample_t sample;
        esp_err_t result = ESP_OK;
        if (s_mock_enabled) {
            make_mock_sample(elapsed_us, &sample);
        } else {
            result = mpu_read_sample(&sample);
        }

        if (result == ESP_OK) {
            consecutive_read_failures = 0;
            ++s_sample_count;
            serial_emit("DATA,%lld,%.4f,%.4f,%.4f,%.3f,%.3f,%.3f",
                        (long long)elapsed_us, sample.ax, sample.ay, sample.az,
                        sample.gx, sample.gy, sample.gz);
            bool streamed = connectivity_stream_motion((uint32_t)elapsed_us,
                    sample.ax, sample.ay, sample.az, sample.gx, sample.gy, sample.gz);
            if (!streamed) offline_store_enqueue((uint32_t)elapsed_us,
                    sample.ax, sample.ay, sample.az, sample.gx, sample.gy, sample.gz);
        } else {
            ++consecutive_read_failures;
            if (consecutive_read_failures <= 2) {
                uint32_t requested_rate = s_sample_rate_hz;
                esp_err_t recovery = mpu_probe_and_configure();
                if (recovery == ESP_OK) recovery = mpu_set_sample_rate(requested_rate);
                if (recovery == ESP_OK) {
                    serial_emit("WARN,MPU_READ_RETRY,ATTEMPT=%u,CAUSE=%s",
                                consecutive_read_failures, esp_err_to_name(result));
                    vTaskDelay(pdMS_TO_TICKS(5));
                    continue;
                }
                serial_emit("WARN,MPU_RECOVERY_FAILED,ATTEMPT=%u,CAUSE=%s",
                            consecutive_read_failures, esp_err_to_name(recovery));
            }
            set_state(STATE_ERROR);
            esp_err_t storage_result = offline_store_finish(true);
            if (storage_result != ESP_OK && storage_result != ESP_ERR_INVALID_STATE)
                serial_emit("WARN,OFFLINE_FINALIZE_FAILED,%s",
                            esp_err_to_name(storage_result));
            serial_emit("ERR,MPU_READ_FAILED,%s", esp_err_to_name(result));
            continue;
        }

        uint32_t period_ms = 1000U / s_sample_rate_hz;
        if (period_ms == 0) {
            period_ms = 1;
        }
        vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(period_ms));
    }
}

static void display_task(void *argument)
{
    (void)argument;
    device_state_t last_state = (device_state_t)-1;
    bool last_mpu = !s_mpu_ready;
    bool last_mock = !s_mock_enabled;
    uint32_t last_rate = 0;
    uint32_t last_duration = 0;
    uint32_t last_revision = 0;
    display_view_t last_view = (display_view_t)-1;
    uint8_t last_page = 0xFF;
    TickType_t last_idle_refresh = 0;
    TickType_t last_pet_refresh = 0;

    while (true) {
        device_state_t state = get_state();
        TickType_t now = xTaskGetTickCount();
        bool idle_refresh_due = s_display_view == DISPLAY_VIEW_IDLE &&
                now - last_idle_refresh >= pdMS_TO_TICKS(1000);
        bool pet_refresh_due = s_display_view == DISPLAY_VIEW_PET &&
                now - last_pet_refresh >= pdMS_TO_TICKS(120);
        if (state != last_state || s_mpu_ready != last_mpu || s_mock_enabled != last_mock ||
            s_sample_rate_hz != last_rate || s_duration_seconds != last_duration ||
            s_display_revision != last_revision || s_display_view != last_view ||
            s_developer_page != last_page || idle_refresh_due || pet_refresh_due) {
            if (pet_refresh_due) ++s_pet_phase;
            display_render_current();
            last_state = state;
            last_mpu = s_mpu_ready;
            last_mock = s_mock_enabled;
            last_rate = s_sample_rate_hz;
            last_duration = s_duration_seconds;
            last_revision = s_display_revision;
            last_view = s_display_view;
            last_page = s_developer_page;
            if (s_display_view == DISPLAY_VIEW_IDLE) last_idle_refresh = now;
            if (s_display_view == DISPLAY_VIEW_PET) last_pet_refresh = now;
        }
        vTaskDelay(pdMS_TO_TICKS(100));
    }
}

static void handle_input_action(input_action_t action, const char *source, void *context)
{
    (void)context;
    device_state_t state = get_state();
    display_request_refresh();
    serial_emit("INPUT,%s,SOURCE=%s", action == INPUT_ACTION_UP ? "UP" :
                action == INPUT_ACTION_DOWN ? "DOWN" :
                action == INPUT_ACTION_LEFT ? "LEFT" :
                action == INPUT_ACTION_RIGHT ? "RIGHT" :
                action == INPUT_ACTION_OK ? "OK" : "BACK",
                source ? source : "unknown");

    if (state == STATE_RECORDING) {
        if (action == INPUT_ACTION_OK) {
            stop_recording(false);
        } else if (action == INPUT_ACTION_BACK) {
            stop_recording(true);
        }
        return;
    }

    if (s_display_view == DISPLAY_VIEW_IDLE) {
        if (action == INPUT_ACTION_OK) {
            labcapsule_set_idle_mode(false);
        } else if (action == INPUT_ACTION_BACK) {
            s_idle_mode = false;
            s_display_view = DISPLAY_VIEW_SETTINGS;
            serial_emit("UI,SETTINGS");
        }
        return;
    }

    if (s_display_view == DISPLAY_VIEW_PET) {
        if (action == INPUT_ACTION_BACK) {
            s_idle_mode = false;
            s_display_view = DISPLAY_VIEW_STATUS;
            serial_emit("UI,HOME");
        } else if (action == INPUT_ACTION_OK) {
            serial_emit("PET,INPUT,TALK");
        } else if (action == INPUT_ACTION_LEFT || action == INPUT_ACTION_RIGHT) {
            serial_emit("PET,INPUT,NEXT_ACTION");
        }
        return;
    }

    if (s_display_view == DISPLAY_VIEW_SETTINGS) {
        if (action == INPUT_ACTION_OK || action == INPUT_ACTION_RIGHT) {
            s_display_view = DISPLAY_VIEW_DEVELOPER;
            s_developer_page = 0;
            serial_emit("UI,DEVELOPER,PAGE=1");
        } else if (action == INPUT_ACTION_BACK || action == INPUT_ACTION_LEFT) {
            s_display_view = DISPLAY_VIEW_STATUS;
            serial_emit("UI,HOME");
        }
        return;
    }

    if (s_display_view == DISPLAY_VIEW_DEVELOPER) {
        if (action == INPUT_ACTION_BACK) {
            s_display_view = DISPLAY_VIEW_SETTINGS;
            serial_emit("UI,SETTINGS");
        } else if (action == INPUT_ACTION_LEFT || action == INPUT_ACTION_UP) {
            s_developer_page = s_developer_page == 0 ? 3 : s_developer_page - 1;
            serial_emit("UI,DEVELOPER,PAGE=%u", (unsigned)(s_developer_page + 1));
        } else if (action == INPUT_ACTION_RIGHT || action == INPUT_ACTION_DOWN) {
            s_developer_page = (uint8_t)((s_developer_page + 1) % 4);
            serial_emit("UI,DEVELOPER,PAGE=%u", (unsigned)(s_developer_page + 1));
        } else if (action == INPUT_ACTION_OK && s_developer_page == 3) {
            s_display_view = DISPLAY_VIEW_COLOR_TEST;
            serial_emit("UI,COLOR_TEST");
        }
        return;
    }

    if (s_display_view == DISPLAY_VIEW_COLOR_TEST) {
        if (action == INPUT_ACTION_OK || action == INPUT_ACTION_BACK ||
            action == INPUT_ACTION_LEFT) {
            s_display_view = DISPLAY_VIEW_DEVELOPER;
            s_developer_page = 3;
            serial_emit("UI,DEVELOPER,PAGE=4");
        }
        return;
    }

    if (s_display_view == DISPLAY_VIEW_WALLPAPER) {
        if (action == INPUT_ACTION_BACK || action == INPUT_ACTION_OK) {
            s_display_view = DISPLAY_VIEW_STATUS;
            serial_emit("UI,HOME");
        }
        return;
    }

    if (action == INPUT_ACTION_OK) {
        start_recording(s_sample_rate_hz, s_duration_seconds);
    } else if (action == INPUT_ACTION_BACK) {
        s_display_view = DISPLAY_VIEW_SETTINGS;
        serial_emit("UI,SETTINGS");
    } else {
        if (action == INPUT_ACTION_UP && s_duration_seconds < MAX_DURATION_SECONDS - 5U) {
            s_duration_seconds += 5U;
        } else if (action == INPUT_ACTION_DOWN && s_duration_seconds > 5U) {
            s_duration_seconds -= 5U;
        } else if (action == INPUT_ACTION_LEFT) {
            s_sample_rate_hz = s_sample_rate_hz <= 100U ? 50U : s_sample_rate_hz / 2U;
        } else if (action == INPUT_ACTION_RIGHT) {
            s_sample_rate_hz = s_sample_rate_hz >= 250U ? 500U : s_sample_rate_hz * 2U;
        }
        serial_emit("CONFIG,RATE=%lu,DURATION=%lu", (unsigned long)s_sample_rate_hz,
                    (unsigned long)s_duration_seconds);
    }
}

static const char *display_view_name(display_view_t view)
{
    switch (view) {
        case DISPLAY_VIEW_SETTINGS: return "settings";
        case DISPLAY_VIEW_DEVELOPER: return "developer";
        case DISPLAY_VIEW_COLOR_TEST: return "test";
        case DISPLAY_VIEW_WALLPAPER: return "wallpaper";
        case DISPLAY_VIEW_MEDIA: return "media";
        case DISPLAY_VIEW_IDLE: return "idle";
        case DISPLAY_VIEW_PET: return "pet";
        case DISPLAY_VIEW_STATUS:
        default: return "home";
    }
}

void labcapsule_build_status_json(char *buffer, size_t buffer_size)
{
    if (!buffer || buffer_size == 0) {
        return;
    }
    offline_store_info_t offline;
    offline_store_get_info(&offline);
    size_t internal_total = heap_caps_get_total_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    size_t internal_free = heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    size_t psram_total = heap_caps_get_total_size(MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    size_t psram_free = heap_caps_get_free_size(MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    const labcapsule_config_t *config = device_config_get();
    snprintf(buffer, buffer_size,
             "{\"version\":\"%s\",\"deviceId\":\"%s\",\"state\":\"%s\",\"view\":\"%s\","
             "\"operationMode\":\"%s\",\"noticeTitle\":\"%s\","
             "\"noticeMessage\":\"%s\","
             "\"mpu\":\"%s\",\"mock\":%s,\"rate\":%lu,\"duration\":%lu,"
             "\"samples\":%lu,\"backlight\":%s,\"brightness\":%u,\"wallpaper\":%s,"
             "\"inputDrivers\":%u,\"offlineSessions\":%lu,"
             "\"offlineSamples\":%lu,\"offlineRecording\":%s,"
             "\"currentMedia\":\"%s\",\"mediaBytes\":%u,"
             "\"gifPlaying\":%s,\"gifFps\":%u,"
             "\"pet\":{\"characterId\":\"%s\",\"proxy\":%s,\"emotion\":\"%s\",\"action\":\"%s\",\"bubble\":%s},"
             "\"hardware\":{\"uptimeSeconds\":%llu,"
             "\"internalFree\":%lu,\"internalTotal\":%lu,"
             "\"psramFree\":%lu,\"psramTotal\":%lu,"
             "\"storageUsed\":%llu,\"storageCapacity\":%llu,"
             "\"bleConnected\":%s,\"staConnected\":%s,\"remoteConnected\":%s},"
             "\"style\":{\"preset\":%u,\"wallpaperOpacity\":%u,"
             "\"panelOpacity\":%u,\"hudOpacity\":%u}}",
             LABCAPSULE_VERSION, labcapsule_device_id(), state_name(get_state()),
             display_view_name(s_display_view),
             s_idle_mode ? "idle" : "experiment", s_idle_title, s_idle_message,
             s_mpu_ready ? "ok" : "missing", s_mock_enabled ? "true" : "false",
             (unsigned long)s_sample_rate_hz, (unsigned long)s_duration_seconds,
             (unsigned long)s_sample_count, s_backlight_commanded_on ? "true" : "false",
             (unsigned)s_backlight_brightness, wallpaper_available() ? "true" : "false",
             (unsigned)input_hub_driver_count(), (unsigned long)offline.sessions,
             (unsigned long)offline.samples, offline.recording ? "true" : "false",
             media_store_clip_available() ? "gif" :
                     (wallpaper_available() ? "image" : "none"),
             (unsigned)media_store_clip_size(),
             s_media_clip_playing ? "true" : "false", (unsigned)s_media_clip_fps,
             config->character_id, config->pet_proxy_enabled ? "true" : "false",
             s_pet_emotion, s_pet_action, s_pet_bubble_valid ? "true" : "false",
             (unsigned long long)(esp_timer_get_time() / 1000000ULL),
             (unsigned long)internal_free, (unsigned long)internal_total,
             (unsigned long)psram_free, (unsigned long)psram_total,
             (unsigned long long)offline.bytes_used,
             (unsigned long long)offline.bytes_capacity,
             connectivity_ble_connected() ? "true" : "false",
             connectivity_sta_connected() ? "true" : "false",
             connectivity_remote_connected() ? "true" : "false",
             (unsigned)s_visual_preset, (unsigned)s_wallpaper_opacity,
               (unsigned)s_panel_opacity, (unsigned)s_hud_opacity);
}

void labcapsule_build_ble_device_json(char *buffer, size_t buffer_size)
{
    if (!buffer || buffer_size == 0) return;
    const labcapsule_config_t *config = device_config_get();
    snprintf(buffer, buffer_size,
             "{\"version\":\"%s\",\"deviceId\":\"%s\",\"state\":\"%s\",\"view\":\"%s\","
             "\"operationMode\":\"%s\",\"mpu\":\"%s\",\"gifPlaying\":%s,"
             "\"gifFps\":%u,\"characterId\":\"%s\",\"petProxy\":%s}",
             LABCAPSULE_VERSION, labcapsule_device_id(), state_name(get_state()),
             display_view_name(s_display_view),
             s_idle_mode ? "idle" : "experiment", s_mpu_ready ? "ok" : "missing",
             s_media_clip_playing ? "true" : "false", (unsigned)s_media_clip_fps,
             config->character_id, config->pet_proxy_enabled ? "true" : "false");
}

void labcapsule_build_hardware_json(char *buffer, size_t buffer_size)
{
    if (!buffer || buffer_size == 0) return;
    offline_store_info_t offline;
    offline_store_get_info(&offline);
    size_t internal_total = heap_caps_get_total_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    size_t internal_free = heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    size_t psram_total = heap_caps_get_total_size(MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    size_t psram_free = heap_caps_get_free_size(MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    snprintf(buffer, buffer_size,
             "{\"ok\":true,\"type\":\"hardware\",\"deviceId\":\"%s\",\"operationMode\":\"%s\","
             "\"uptimeSeconds\":%llu,\"internalFree\":%lu,\"internalTotal\":%lu,"
             "\"psramFree\":%lu,\"psramTotal\":%lu,"
             "\"storageUsed\":%llu,\"storageCapacity\":%llu,"
             "\"bleConnected\":%s,\"staConnected\":%s,\"remoteConnected\":%s}",
             labcapsule_device_id(), s_idle_mode ? "idle" : "experiment",
             (unsigned long long)(esp_timer_get_time() / 1000000ULL),
             (unsigned long)internal_free, (unsigned long)internal_total,
             (unsigned long)psram_free, (unsigned long)psram_total,
             (unsigned long long)offline.bytes_used,
             (unsigned long long)offline.bytes_capacity,
             connectivity_ble_connected() ? "true" : "false",
             connectivity_sta_connected() ? "true" : "false",
             connectivity_remote_connected() ? "true" : "false");
}

void labcapsule_show_wallpaper(void)
{
    if (wallpaper_available()) {
        s_display_view = DISPLAY_VIEW_STATUS;
        display_request_refresh();
        serial_emit("UI,WALLPAPER_BACKGROUND");
    }
}

esp_err_t labcapsule_media_frame_begin(size_t payload_size)
{
    return labcapsule_media_region_begin(payload_size, 0, 0, TFT_WIDTH, TFT_HEIGHT,
                                         LABCAPSULE_MEDIA_RAW565);
}

esp_err_t labcapsule_media_region_begin(size_t payload_size, uint16_t x, uint16_t y,
                                        uint16_t width, uint16_t height,
                                        labcapsule_media_encoding_t encoding)
{
    if (!s_media_receive_buffer || s_media_receive_active || payload_size == 0 ||
        payload_size > WALLPAPER_PAYLOAD_BYTES || width == 0 || height == 0 ||
        x + width > TFT_WIDTH || y + height > TFT_HEIGHT ||
        encoding > LABCAPSULE_MEDIA_DELTA332) return ESP_ERR_INVALID_ARG;
    size_t pixels = (size_t)width * height;
    if ((encoding == LABCAPSULE_MEDIA_RAW565 && payload_size != pixels * 2U) ||
        (encoding == LABCAPSULE_MEDIA_RGB332 && payload_size != pixels) ||
        ((encoding == LABCAPSULE_MEDIA_RLE565 ||
          encoding == LABCAPSULE_MEDIA_RLE332) && payload_size < 2U) ||
        (encoding == LABCAPSULE_MEDIA_DELTA332 && payload_size < 4U)) {
        return ESP_ERR_INVALID_SIZE;
    }
    if (s_display_view != DISPLAY_VIEW_MEDIA &&
        !(s_display_view == DISPLAY_VIEW_PET && device_config_get()->pet_proxy_enabled) &&
        (x != 0 || y != 0 || width != TFT_WIDTH || height != TFT_HEIGHT)) {
        return ESP_ERR_INVALID_STATE;
    }
    s_media_received = 0;
    s_media_x = x;
    s_media_y = y;
    s_media_width = width;
    s_media_height = height;
    s_media_encoding = encoding;
    s_media_receive_active = true;
    return ESP_OK;
}

esp_err_t labcapsule_media_frame_write(const uint8_t *data, size_t length)
{
    if (!s_media_receive_active || !data || length == 0 ||
        s_media_received + length > WALLPAPER_PAYLOAD_BYTES) return ESP_ERR_INVALID_ARG;
    memcpy(s_media_receive_buffer + s_media_received, data, length);
    s_media_received += length;
    return ESP_OK;
}

esp_err_t labcapsule_media_frame_finish(uint32_t duration_ms)
{
    if (!s_media_receive_active) {
        labcapsule_media_frame_abort();
        return ESP_ERR_INVALID_STATE;
    }
    const size_t payload_bytes = s_media_received;
    xSemaphoreTake(s_display_mutex, portMAX_DELAY);
    size_t source = 0;
    size_t pixel = 0;
    const size_t pixels = (size_t)s_media_width * s_media_height;
    esp_err_t decode_result = ESP_OK;
    if (s_media_encoding == LABCAPSULE_MEDIA_DELTA332) {
        while (source < s_media_received) {
            if (source + 3 > s_media_received) {
                decode_result = ESP_ERR_INVALID_SIZE;
                break;
            }
            size_t skip = (size_t)s_media_receive_buffer[source] |
                    ((size_t)s_media_receive_buffer[source + 1] << 8);
            source += 2;
            size_t run = s_media_receive_buffer[source++];
            if (pixel + skip > pixels || source + run > s_media_received ||
                pixel + skip + run > pixels) {
                decode_result = ESP_ERR_INVALID_SIZE;
                break;
            }
            pixel += skip;
            for (size_t count = 0; count < run; ++count, ++pixel) {
                uint8_t packed = s_media_receive_buffer[source++];
                uint8_t red = (uint8_t)(((packed >> 5) & 0x07U) * 255U / 7U);
                uint8_t green = (uint8_t)(((packed >> 2) & 0x07U) * 255U / 7U);
                uint8_t blue = (uint8_t)((packed & 0x03U) * 255U / 3U);
                size_t row = pixel / s_media_width;
                size_t column = pixel % s_media_width;
                size_t target = ((size_t)s_media_y + row) * TFT_WIDTH +
                        s_media_x + column;
                s_media_canvas[target] = rgb565(red, green, blue);
            }
        }
    } else {
    while (pixel < pixels) {
        uint16_t color = 0;
        size_t run = 1;
        if (s_media_encoding == LABCAPSULE_MEDIA_RAW565) {
            if (source + 2 > s_media_received) { decode_result = ESP_ERR_INVALID_SIZE; break; }
            color = (uint16_t)(s_media_receive_buffer[source] |
                               ((uint16_t)s_media_receive_buffer[source + 1] << 8));
            source += 2;
        } else if (s_media_encoding == LABCAPSULE_MEDIA_RGB332) {
            if (source >= s_media_received) { decode_result = ESP_ERR_INVALID_SIZE; break; }
            uint8_t packed = s_media_receive_buffer[source++];
            uint8_t red = (uint8_t)(((packed >> 5) & 0x07U) * 255U / 7U);
            uint8_t green = (uint8_t)(((packed >> 2) & 0x07U) * 255U / 7U);
            uint8_t blue = (uint8_t)((packed & 0x03U) * 255U / 3U);
            color = rgb565(red, green, blue);
        } else if (s_media_encoding == LABCAPSULE_MEDIA_RLE565) {
            if (source + 3 > s_media_received) { decode_result = ESP_ERR_INVALID_SIZE; break; }
            run = s_media_receive_buffer[source++];
            color = (uint16_t)(s_media_receive_buffer[source] |
                               ((uint16_t)s_media_receive_buffer[source + 1] << 8));
            source += 2;
        } else {
            if (source + 2 > s_media_received) { decode_result = ESP_ERR_INVALID_SIZE; break; }
            run = s_media_receive_buffer[source++];
            uint8_t packed = s_media_receive_buffer[source++];
            uint8_t red = (uint8_t)(((packed >> 5) & 0x07U) * 255U / 7U);
            uint8_t green = (uint8_t)(((packed >> 2) & 0x07U) * 255U / 7U);
            uint8_t blue = (uint8_t)((packed & 0x03U) * 255U / 3U);
            color = rgb565(red, green, blue);
        }
        if (run == 0 || pixel + run > pixels) { decode_result = ESP_ERR_INVALID_SIZE; break; }
        for (size_t count = 0; count < run; ++count, ++pixel) {
            size_t row = pixel / s_media_width;
            size_t column = pixel % s_media_width;
            size_t target = ((size_t)s_media_y + row) * TFT_WIDTH + s_media_x + column;
            s_media_canvas[target] = color;
        }
    }
    if (source != s_media_received || pixel != pixels) decode_result = ESP_ERR_INVALID_SIZE;
    }
    if (decode_result != ESP_OK) {
        xSemaphoreGive(s_display_mutex);
        labcapsule_media_frame_abort();
        return decode_result;
    }
    bool pet_proxy = device_config_get()->pet_proxy_enabled;
    s_display_view = pet_proxy ? DISPLAY_VIEW_PET : DISPLAY_VIEW_MEDIA;
    s_media_frame_duration_ms = duration_ms < 20 ? 20 : duration_ms;
    if (pet_proxy) {
        display_render_pet();
    } else {
        s_live_background_override = s_media_canvas;
        display_render_state(get_state());
        s_live_background_override = NULL;
    }
    esp_err_t result = display_present();
    xSemaphoreGive(s_display_mutex);
    s_media_receive_active = false;
    s_media_received = 0;
    serial_emit("MEDIA,FRAME,%ux%u@%u,%u,ENC=%u,BYTES=%u,DURATION=%lu",
                (unsigned)s_media_width, (unsigned)s_media_height,
                (unsigned)s_media_x, (unsigned)s_media_y,
                (unsigned)s_media_encoding, (unsigned)payload_bytes,
                (unsigned long)s_media_frame_duration_ms);
    return result;
}

void labcapsule_media_frame_abort(void)
{
    s_media_receive_active = false;
    s_media_received = 0;
    s_media_x = s_media_y = s_media_width = s_media_height = 0;
    s_media_encoding = LABCAPSULE_MEDIA_RAW565;
}

esp_err_t labcapsule_media_clip_set_fps(uint8_t fps)
{
    if (fps < 1 || fps > LABCAPSULE_MEDIA_MAX_FPS) return ESP_ERR_INVALID_ARG;
    s_media_clip_fps = fps;
    serial_emit("OK,GIF,FPS=%u", (unsigned)fps);
    return ESP_OK;
}

esp_err_t labcapsule_media_clip_start(void)
{
    if (!media_store_clip_available()) return ESP_ERR_NOT_FOUND;
    ++s_media_clip_generation;
    s_media_clip_playing = true;
    s_idle_mode = false;
    serial_emit("OK,GIF,PLAY,FPS=%u,BYTES=%u", (unsigned)s_media_clip_fps,
                (unsigned)media_store_clip_size());
    return ESP_OK;
}

void labcapsule_media_clip_stop(void)
{
    s_media_clip_playing = false;
    ++s_media_clip_generation;
    if (s_display_view == DISPLAY_VIEW_MEDIA) s_display_view = DISPLAY_VIEW_STATUS;
    display_request_refresh();
    serial_emit("OK,GIF,STOP");
}

bool labcapsule_media_clip_playing(void)
{
    return s_media_clip_playing;
}

uint8_t labcapsule_media_clip_fps(void)
{
    return s_media_clip_fps;
}

static esp_err_t display_stored_media_frame(const media_store_frame_t *frame,
                                            const uint8_t *payload)
{
    if (!frame || frame->payload_size == 0) return ESP_OK;
    esp_err_t result = labcapsule_media_region_begin(frame->payload_size, frame->x, frame->y,
            frame->width, frame->height, frame->encoding);
    if (result != ESP_OK) return result;
    result = labcapsule_media_frame_write(payload, frame->payload_size);
    if (result == ESP_OK) result = labcapsule_media_frame_finish(
            1000U / (s_media_clip_fps ? s_media_clip_fps : 1U));
    else labcapsule_media_frame_abort();
    return result;
}

static void media_playback_task(void *argument)
{
    (void)argument;
    while (true) {
        if (!s_media_clip_playing || !media_store_clip_available()) {
            vTaskDelay(pdMS_TO_TICKS(100));
            continue;
        }
        uint32_t generation = s_media_clip_generation;
        media_store_reader_t reader;
        media_store_frame_t frame;
        if (media_store_reader_open(&reader) != ESP_OK) {
            s_media_clip_playing = false;
            continue;
        }
        uint8_t source_fps = (uint8_t)((1000U + reader.interval_ms / 2U) /
                                       reader.interval_ms);
        if (source_fps >= 1 && source_fps <= LABCAPSULE_MEDIA_MAX_FPS)
            s_media_clip_fps = source_fps;
        esp_err_t result = media_store_reader_bootstrap(&reader, &frame,
                s_media_receive_buffer, WALLPAPER_PAYLOAD_BYTES);
        bool bootstrap = true;
        while (result == ESP_OK && s_media_clip_playing &&
               generation == s_media_clip_generation) {
            int64_t started = esp_timer_get_time();
            result = display_stored_media_frame(&frame, s_media_receive_buffer);
            if (result != ESP_OK) break;
            uint32_t fps = s_media_clip_fps;
            if (fps < 1) fps = 1;
            if (fps > LABCAPSULE_MEDIA_MAX_FPS) fps = LABCAPSULE_MEDIA_MAX_FPS;
            int64_t remaining_us = 1000000LL / fps - (esp_timer_get_time() - started);
            if (remaining_us > 1000) vTaskDelay(pdMS_TO_TICKS((uint32_t)(remaining_us / 1000)));
            if (bootstrap) bootstrap = false;
            result = media_store_reader_next(&reader, &frame, s_media_receive_buffer,
                                             WALLPAPER_PAYLOAD_BYTES);
        }
        media_store_reader_close(&reader);
        if (result != ESP_OK && generation == s_media_clip_generation) {
            s_media_clip_playing = false;
            serial_emit("ERR,GIF,PLAYBACK=%s", esp_err_to_name(result));
        }
    }
}

esp_err_t labcapsule_set_brightness(uint8_t percent)
{
    if (percent > 100) return ESP_ERR_INVALID_ARG;
    s_backlight_brightness = percent;
    display_set_backlight(percent > 0);
    display_request_refresh();
    serial_emit("DISPLAY,BRIGHTNESS=%u", (unsigned)percent);
    return ESP_OK;
}

esp_err_t labcapsule_set_visual_style(uint8_t preset, uint8_t wallpaper_opacity,
                                      uint8_t panel_opacity, uint8_t hud_opacity)
{
    if (preset > 2 || wallpaper_opacity > 100 || panel_opacity > 100 ||
        hud_opacity > 100) return ESP_ERR_INVALID_ARG;
    s_visual_preset = preset;
    s_wallpaper_opacity = wallpaper_opacity;
    s_panel_opacity = panel_opacity;
    s_hud_opacity = hud_opacity;
    if (s_display_view == DISPLAY_VIEW_WALLPAPER) {
        s_display_view = DISPLAY_VIEW_STATUS;
    }
    display_request_refresh();
    serial_emit("DISPLAY,STYLE=%u,WALL=%u,PANEL=%u,HUD=%u", (unsigned)preset,
                (unsigned)wallpaper_opacity, (unsigned)panel_opacity,
                (unsigned)hud_opacity);
    return ESP_OK;
}

esp_err_t labcapsule_start_experiment(uint32_t rate_hz, uint32_t duration_seconds)
{
    return start_recording(rate_hz, duration_seconds);
}

static void sanitize_idle_text(const char *source, char *target, size_t capacity,
                               const char *fallback)
{
    if (!target || capacity == 0) return;
    size_t written = 0;
    bool prior_space = false;
    for (size_t index = 0; source && source[index] && written + 1 < capacity; ++index) {
        unsigned char value = (unsigned char)source[index];
        char output = '\0';
        if (value < 128 && isalnum(value)) output = (char)toupper(value);
        else if (value == '-' || value == '.' || value == ':') output = (char)value;
        else if (value < 128 && isspace(value)) output = ' ';
        else if (value >= 128) output = ' ';
        if (!output || (output == ' ' && (written == 0 || prior_space))) continue;
        target[written++] = output;
        prior_space = output == ' ';
    }
    while (written > 0 && target[written - 1] == ' ') --written;
    target[written] = '\0';
    if (written == 0 && fallback) strlcpy(target, fallback, capacity);
}

esp_err_t labcapsule_set_idle_mode(bool idle)
{
    if (idle && get_state() == STATE_RECORDING) return ESP_ERR_INVALID_STATE;
    s_idle_mode = idle;
    s_display_view = idle ? DISPLAY_VIEW_IDLE : DISPLAY_VIEW_STATUS;
    display_request_refresh();
    serial_emit("MODE,%s", idle ? "IDLE" : "EXPERIMENT");
    return ESP_OK;
}

esp_err_t labcapsule_set_idle_notice(const char *title, const char *message)
{
    sanitize_idle_text(title, s_idle_title, sizeof(s_idle_title), "DEVICE IDLE");
    sanitize_idle_text(message, s_idle_message, sizeof(s_idle_message), "READY FOR LINK");
    display_request_refresh();
    serial_emit("NOTICE,%s,%s", s_idle_title, s_idle_message);
    return ESP_OK;
}

esp_err_t labcapsule_remote_action(const char *action, char *response, size_t response_size)
{
    if (!action || !response || response_size == 0) {
        return ESP_ERR_INVALID_ARG;
    }
    char normalized[160];
    size_t index = 0;
    while (action[index] && index < sizeof(normalized) - 1) {
        char value = action[index];
        normalized[index] = value == '-' ? '_' : (char)toupper((unsigned char)value);
        ++index;
    }
    normalized[index] = '\0';

    if (strncmp(normalized, "GIF_FPS:", 8) == 0) {
        unsigned fps = (unsigned)strtoul(normalized + 8, NULL, 10);
        esp_err_t result = labcapsule_media_clip_set_fps((uint8_t)fps);
        snprintf(response, response_size, result == ESP_OK ? "GIF FPS applied" :
                 "GIF FPS must be 1..8");
        return result;
    } else if (strcmp(normalized, "GIF_PLAY") == 0) {
        esp_err_t result = labcapsule_media_clip_start();
        snprintf(response, response_size, result == ESP_OK ? "stored GIF playing" :
                 "stored GIF not found");
        return result;
    } else if (strcmp(normalized, "GIF_STOP") == 0) {
        labcapsule_media_clip_stop();
        snprintf(response, response_size, "stored GIF stopped");
        return ESP_OK;
    } else if (strncmp(normalized, "HOST:", 5) == 0) {
        unsigned cpu = 0, ram = 0, disk = 0;
        int temperature = -1;
        if (sscanf(normalized + 5, "%u:%u:%u:%d", &cpu, &ram, &disk,
                   &temperature) != 4 || cpu > 100 || ram > 100 || disk > 100 ||
            temperature < -1 || temperature > 150) {
            snprintf(response, response_size, "expected HOST:cpu:ram:disk:temp");
            return ESP_ERR_INVALID_ARG;
        }
        s_host_cpu_percent = (uint8_t)cpu;
        s_host_ram_percent = (uint8_t)ram;
        s_host_disk_percent = (uint8_t)disk;
        s_host_temperature_c = (int16_t)temperature;
        s_host_last_heartbeat_us = esp_timer_get_time();
        s_host_link_active = true;
        if (get_state() != STATE_RECORDING && s_display_view != DISPLAY_VIEW_PET) {
            s_idle_mode = true;
            s_display_view = DISPLAY_VIEW_IDLE;
        }
        display_request_refresh();
        snprintf(response, response_size, "host telemetry applied");
        return ESP_OK;
    } else if (strncmp(normalized, "STYLE:", 6) == 0) {
        unsigned preset = 0, wallpaper_opacity = 0, panel_opacity = 0, hud_opacity = 0;
        if (sscanf(normalized + 6, "%u:%u:%u:%u", &preset, &wallpaper_opacity,
                   &panel_opacity, &hud_opacity) != 4) {
            snprintf(response, response_size, "expected STYLE:preset:wall:panel:hud");
            return ESP_ERR_INVALID_ARG;
        }
        if (preset > 2 || wallpaper_opacity > 100 || panel_opacity > 100 ||
            hud_opacity > 100) {
            snprintf(response, response_size, "style values out of range");
            return ESP_ERR_INVALID_ARG;
        }
        esp_err_t result = labcapsule_set_visual_style((uint8_t)preset,
                (uint8_t)wallpaper_opacity, (uint8_t)panel_opacity,
                (uint8_t)hud_opacity);
        snprintf(response, response_size, result == ESP_OK ? "visual style applied" :
                 "visual style rejected");
        return result;
    } else if (strncmp(normalized, "START:", 6) == 0) {
        unsigned rate = 0;
        unsigned duration = 0;
        if (sscanf(normalized + 6, "%u:%u", &rate, &duration) != 2) {
            snprintf(response, response_size, "expected START:rate:duration");
            return ESP_ERR_INVALID_ARG;
        }
        esp_err_t result = labcapsule_start_experiment(rate, duration);
        snprintf(response, response_size, result == ESP_OK ? "experiment started" :
                 "experiment rejected");
        return result;
    } else if (strcmp(normalized, "STOP") == 0) {
        if (get_state() != STATE_RECORDING) {
            snprintf(response, response_size, "no active experiment");
            return ESP_ERR_INVALID_STATE;
        }
        stop_recording(false);
        snprintf(response, response_size, "experiment stopped and retained");
        return ESP_OK;
    } else if (strcmp(normalized, "ABORT") == 0) {
        if (get_state() != STATE_RECORDING) {
            snprintf(response, response_size, "no active experiment");
            return ESP_ERR_INVALID_STATE;
        }
        stop_recording(true);
        snprintf(response, response_size, "experiment aborted");
        return ESP_OK;
    } else if (strcmp(normalized, "MOCK_ON") == 0 ||
               strcmp(normalized, "MOCK_OFF") == 0) {
        s_mock_enabled = strcmp(normalized, "MOCK_ON") == 0;
        display_request_refresh();
        snprintf(response, response_size, "mock %s", s_mock_enabled ? "enabled" : "disabled");
        return ESP_OK;
    } else if (strncmp(normalized, "PET_STATE:", 10) == 0) {
        char *motion = strchr(normalized + 10, ':');
        if (!motion || get_state() == STATE_RECORDING) {
            snprintf(response, response_size, "expected PET_STATE:emotion:action");
            return ESP_ERR_INVALID_ARG;
        }
        *motion++ = '\0';
        if (!normalized[10] || !motion[0] || strlen(normalized + 10) >= sizeof(s_pet_emotion) ||
            strlen(motion) >= sizeof(s_pet_action)) {
            snprintf(response, response_size, "pet state value too long");
            return ESP_ERR_INVALID_ARG;
        }
        strlcpy(s_pet_emotion, normalized + 10, sizeof(s_pet_emotion));
        strlcpy(s_pet_action, motion, sizeof(s_pet_action));
        s_pet_phase = 0;
        s_idle_mode = true;
        s_display_view = DISPLAY_VIEW_PET;
        display_request_refresh();
        snprintf(response, response_size, "pet state applied");
        return ESP_OK;
    } else if (strncmp(normalized, "PET_IDENTITY:", 13) == 0) {
        const char *raw_value = action + 13;
        const char *raw_proxy = strrchr(raw_value, ':');
        if (!raw_proxy || raw_proxy == raw_value) {
            snprintf(response, response_size, "expected PET_IDENTITY:id:proxy");
            return ESP_ERR_INVALID_ARG;
        }
        char character_id[sizeof(((labcapsule_config_t *)0)->character_id)] = {0};
        size_t character_length = (size_t)(raw_proxy - raw_value);
        if (character_length >= sizeof(character_id)) {
            snprintf(response, response_size, "pet identity too long");
            return ESP_ERR_INVALID_ARG;
        }
        memcpy(character_id, raw_value, character_length);
        const char *proxy = strrchr(normalized + 13, ':') + 1;
        esp_err_t result = labcapsule_set_character_identity(
                character_id, strcmp(proxy, "PROXY") == 0 || strcmp(proxy, "ON") == 0);
        snprintf(response, response_size, result == ESP_OK ? "pet identity applied" :
                 "pet identity rejected");
        return result;
    } else if (strcmp(normalized, "PET_CLEAR") == 0) {
        memset(s_pet_bubble, 0, sizeof(s_pet_bubble));
        s_pet_bubble_valid = false;
        display_request_refresh();
        snprintf(response, response_size, "pet bubble cleared");
        return ESP_OK;
    } else if (strcmp(normalized, "MODE:IDLE") == 0) {
        esp_err_t result = labcapsule_set_idle_mode(true);
        snprintf(response, response_size, result == ESP_OK ? "idle dashboard enabled" :
                 "cannot enter idle while recording");
        return result;
    } else if (strcmp(normalized, "MODE:EXPERIMENT") == 0) {
        esp_err_t result = labcapsule_set_idle_mode(false);
        snprintf(response, response_size, "experiment console enabled");
        return result;
    } else if (strncmp(normalized, "NOTICE:", 7) == 0) {
        char *message = strchr(normalized + 7, '|');
        if (!message) {
            snprintf(response, response_size, "expected NOTICE:title|message");
            return ESP_ERR_INVALID_ARG;
        }
        *message++ = '\0';
        esp_err_t result = labcapsule_set_idle_notice(normalized + 7, message);
        snprintf(response, response_size, "idle notice updated");
        return result;
    } else if (strcmp(normalized, "HOME") == 0 || strcmp(normalized, "STATUS") == 0) {
        s_idle_mode = false;
        s_display_view = DISPLAY_VIEW_STATUS;
    } else if (strcmp(normalized, "SETTINGS") == 0) {
        s_display_view = DISPLAY_VIEW_SETTINGS;
    } else if (strcmp(normalized, "PET") == 0) {
        if (get_state() == STATE_RECORDING) {
            snprintf(response, response_size, "cannot show pet while recording");
            return ESP_ERR_INVALID_STATE;
        }
        s_idle_mode = true;
        s_display_view = DISPLAY_VIEW_PET;
    } else if (strcmp(normalized, "DEVELOPER") == 0 || strcmp(normalized, "DEV") == 0) {
        s_display_view = DISPLAY_VIEW_DEVELOPER;
        s_developer_page = 0;
    } else if (strcmp(normalized, "TEST") == 0 || strcmp(normalized, "COLOR") == 0) {
        s_display_view = DISPLAY_VIEW_COLOR_TEST;
    } else if (strcmp(normalized, "WALLPAPER") == 0) {
        if (!wallpaper_available()) {
            snprintf(response, response_size, "wallpaper not uploaded");
            return ESP_ERR_NOT_FOUND;
        }
        s_display_view = DISPLAY_VIEW_STATUS;
    } else if (strcmp(normalized, "INVERT") == 0) {
        s_display_inverted = !s_display_inverted;
        if (s_display_ready) {
            esp_lcd_panel_invert_color(s_panel, s_display_inverted);
        }
    } else if (strcmp(normalized, "BL_ON") == 0 ||
               strcmp(normalized, "BACKLIGHT_ON") == 0) {
        display_set_backlight(true);
    } else if (strcmp(normalized, "BL_OFF") == 0 ||
               strcmp(normalized, "BACKLIGHT_OFF") == 0) {
        display_set_backlight(false);
    } else if (strncmp(normalized, "BRIGHTNESS_", 11) == 0) {
        unsigned brightness = (unsigned)strtoul(normalized + 11, NULL, 10);
        if (brightness > 100) {
            snprintf(response, response_size, "brightness must be 0..100");
            return ESP_ERR_INVALID_ARG;
        }
        labcapsule_set_brightness((uint8_t)brightness);
    } else {
        input_action_t virtual_action = INPUT_ACTION_COUNT;
        if (strcmp(normalized, "UP") == 0) virtual_action = INPUT_ACTION_UP;
        else if (strcmp(normalized, "DOWN") == 0) virtual_action = INPUT_ACTION_DOWN;
        else if (strcmp(normalized, "LEFT") == 0) virtual_action = INPUT_ACTION_LEFT;
        else if (strcmp(normalized, "RIGHT") == 0) virtual_action = INPUT_ACTION_RIGHT;
        else if (strcmp(normalized, "OK") == 0) virtual_action = INPUT_ACTION_OK;
        else if (strcmp(normalized, "BACK") == 0) virtual_action = INPUT_ACTION_BACK;
        if (virtual_action == INPUT_ACTION_COUNT) {
            snprintf(response, response_size, "unknown action");
            return ESP_ERR_NOT_SUPPORTED;
        }
        input_hub_emit(virtual_action, "remote");
    }
    display_request_refresh();
    snprintf(response, response_size, "applied");
    serial_emit("REMOTE,%s", normalized);
    return ESP_OK;
}

static input_action_mask_t gpio_buttons_poll(void *context)
{
    (void)context;
    input_action_mask_t pressed = 0;
    if (gpio_get_level(PIN_BUTTON_UP) == 0) pressed |= INPUT_ACTION_BIT(INPUT_ACTION_UP);
    if (gpio_get_level(PIN_BUTTON_DOWN) == 0) pressed |= INPUT_ACTION_BIT(INPUT_ACTION_DOWN);
    if (gpio_get_level(PIN_BUTTON_LEFT) == 0) pressed |= INPUT_ACTION_BIT(INPUT_ACTION_LEFT);
    if (gpio_get_level(PIN_BUTTON_RIGHT) == 0) pressed |= INPUT_ACTION_BIT(INPUT_ACTION_RIGHT);
    if (gpio_get_level(PIN_BUTTON_OK) == 0) pressed |= INPUT_ACTION_BIT(INPUT_ACTION_OK);
    if (gpio_get_level(PIN_BUTTON_BACK) == 0) pressed |= INPUT_ACTION_BIT(INPUT_ACTION_BACK);
    return pressed;
}

static void input_task(void *argument)
{
    (void)argument;
    while (true) {
        input_hub_poll();
        vTaskDelay(pdMS_TO_TICKS(10));
    }
}

void app_main(void)
{
    esp_log_level_set("*", ESP_LOG_INFO);

    ESP_ERROR_CHECK(serial_init());
    (void)labcapsule_device_id();
    serial_emit("BOOT,LABCAPSULE,%s", LABCAPSULE_VERSION);
    serial_emit("PINOUT,I2C=8/9,TFT=12/11/10/7/6/5,BUTTONS=14/15/16/17/18/13");

    ESP_ERROR_CHECK(buttons_init());

    esp_err_t wallpaper_result = wallpaper_init();
    if (wallpaper_result != ESP_OK) {
        ESP_LOGW(TAG, "Wallpaper storage unavailable: %s", esp_err_to_name(wallpaper_result));
    }

    esp_err_t offline_result = offline_store_init();
    if (offline_result != ESP_OK) {
        ESP_LOGW(TAG, "Offline storage unavailable: %s", esp_err_to_name(offline_result));
        serial_emit("WARN,OFFLINE_STORAGE_INIT_FAILED,%s", esp_err_to_name(offline_result));
    }

    esp_err_t media_store_result = media_store_init();
    if (media_store_result != ESP_OK) {
        ESP_LOGW(TAG, "Current media storage unavailable: %s",
                 esp_err_to_name(media_store_result));
        serial_emit("WARN,MEDIA_STORAGE_INIT_FAILED,%s",
                    esp_err_to_name(media_store_result));
    }

    esp_err_t display_result = display_init();
    if (display_result != ESP_OK) {
        ESP_LOGE(TAG, "Display init failed: %s", esp_err_to_name(display_result));
        serial_emit("WARN,DISPLAY_INIT_FAILED,%s", esp_err_to_name(display_result));
    } else {
        serial_emit("OK,DISPLAY,ST7789,SPI=10MHZ,BL_PULSES=3");
    }

    esp_err_t mpu_result = mpu_init();
    if (mpu_result == ESP_OK) {
        serial_emit("OK,MPU6050,ADDRESS=0x%02X", s_mpu_address);
    } else {
        ESP_LOGW(TAG, "MPU6050 not ready: %s", esp_err_to_name(mpu_result));
        serial_emit("WARN,MPU6050_NOT_FOUND,SDA=8,SCL=9");
    }
    ESP_ERROR_CHECK(sensor_hub_init(s_i2c_bus, s_mpu_mutex));
    sensor_hub_set_primary_ready("mpu6050", s_mpu_ready);

    ESP_ERROR_CHECK(input_hub_init(handle_input_action, NULL));
    const input_driver_t gpio_driver = {
        .id = "gpio-buttons",
        .poll = gpio_buttons_poll,
        .debounce_ms = 30,
    };
    ESP_ERROR_CHECK(input_hub_register(&gpio_driver));

    set_state(STATE_READY);
    display_render_state(STATE_READY);

    xTaskCreate(serial_task, "serial_commands", 4096, NULL, 8, NULL);
    xTaskCreate(sampling_task, "motion_sampling", 4096, NULL, 9, NULL);
    xTaskCreate(display_task, "display_state", 4096, NULL, 4, NULL);
    xTaskCreate(input_task, "input_hub", 3072, NULL, 5, NULL);
    xTaskCreate(media_playback_task, "media_playback", 4096, NULL, 5, NULL);
    if (media_store_clip_available()) labcapsule_media_clip_start();

    esp_err_t connectivity_result = connectivity_start();
    if (connectivity_result == ESP_OK) {
        serial_emit("OK,CONNECTIVITY,WIFI=192.168.4.1,BLE=READY");
    } else {
        ESP_LOGE(TAG, "Connectivity unavailable: %s", esp_err_to_name(connectivity_result));
        serial_emit("WARN,CONNECTIVITY_FAILED,%s", esp_err_to_name(connectivity_result));
    }

    if (device_config_get()->pet_proxy_enabled && media_store_clip_available()) {
        s_idle_mode = true;
        s_display_view = DISPLAY_VIEW_PET;
        display_request_refresh();
    }

    serial_emit("READY,TYPE=PING_OR_HELP");
    emit_status();
    emit_display_diagnostics();
}
