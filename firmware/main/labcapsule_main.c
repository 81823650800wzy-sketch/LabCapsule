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
#include "esp_check.h"
#include "esp_err.h"
#include "esp_lcd_panel_commands.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_panel_vendor.h"
#include "esp_log.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "labcapsule_control.h"
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
    DISPLAY_VIEW_STATUS = 0,
    DISPLAY_VIEW_SETTINGS,
    DISPLAY_VIEW_DEVELOPER,
    DISPLAY_VIEW_COLOR_TEST,
    DISPLAY_VIEW_WALLPAPER,
    DISPLAY_VIEW_MEDIA,
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

static bool s_usb_serial_ready = false;
static bool s_mpu_ready = false;
static bool s_display_ready = false;
static bool s_display_inverted = true;
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
        usb_serial_jtag_write_bytes(buffer, (size_t)length, pdMS_TO_TICKS(20));
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
    esp_err_t uart_result = uart_driver_install(UART_NUM_0, 2048, 0, 0, NULL, 0);
    if (uart_result != ESP_OK && uart_result != ESP_ERR_INVALID_STATE) {
        return uart_result;
    }

    usb_serial_jtag_driver_config_t usb_config = {
        .tx_buffer_size = 2048,
        .rx_buffer_size = 2048,
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

static esp_err_t mpu_set_sample_rate(uint32_t rate_hz)
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
    return mpu_set_sample_rate(DEFAULT_SAMPLE_RATE_HZ);
}

static esp_err_t mpu_read_sample(motion_sample_t *sample)
{
    uint8_t raw[14];
    ESP_RETURN_ON_ERROR(mpu_read_registers(MPU6050_REG_ACCEL_XOUT_H, raw, sizeof(raw)),
                        TAG, "MPU6050 sample read failed");

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
    display_text(24, 250, s_mock_enabled ? "SIMULATION ON" : "SENSOR MODE", 2,
                 theme.muted);

    char config_text[32];
    snprintf(config_text, sizeof(config_text), "%luHZ  %luSEC",
             (unsigned long)s_sample_rate_hz, (unsigned long)s_duration_seconds);
    display_text(24, 280, config_text, 2, theme.text);
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

    portENTER_CRITICAL(&s_state_lock);
    s_sample_rate_hz = rate_hz;
    s_duration_seconds = duration_seconds;
    s_sample_count = 0;
    s_recording_started_us = esp_timer_get_time();
    s_state = STATE_RECORDING;
    portEXIT_CRITICAL(&s_state_lock);
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
    } else if (strcmp(action, "HOME") == 0 || strcmp(action, "STATUS") == 0) {
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

static void handle_command(char *line)
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
        serial_emit("PONG,LABCAPSULE,%s", LABCAPSULE_VERSION);
    } else if (strcmp(command, "STATUS") == 0) {
        emit_status();
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
        serial_emit("COMMANDS,PING|STATUS|START[,RATE,DURATION]|STOP|ABORT|MOCK,ON|OFF");
        serial_emit("COMMANDS,DISPLAY[,DEV|TEST|WALLPAPER|SETTINGS|HOME|INVERT|BL,ON|OFF]");
        serial_emit("COMMANDS,STYLE,PRESET,WALL,PANEL,HUD");
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
            handle_command(line);
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
    uint8_t byte;
    while (true) {
        int uart_bytes = uart_read_bytes(UART_NUM_0, &byte, 1, pdMS_TO_TICKS(5));
        if (uart_bytes == 1) {
            accept_serial_byte(SERIAL_SOURCE_UART, byte);
        }
        if (s_usb_serial_ready) {
            int usb_bytes = usb_serial_jtag_read_bytes(&byte, 1, 0);
            if (usb_bytes == 1) {
                accept_serial_byte(SERIAL_SOURCE_USB, byte);
            }
        }
    }
}

static void sampling_task(void *argument)
{
    (void)argument;
    TickType_t last_wake = xTaskGetTickCount();
    device_state_t prior_state = STATE_BOOT;

    while (true) {
        device_state_t state = get_state();
        if (state != STATE_RECORDING) {
            prior_state = state;
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
            ++s_sample_count;
            serial_emit("DATA,%lld,%.4f,%.4f,%.4f,%.3f,%.3f,%.3f",
                        (long long)elapsed_us, sample.ax, sample.ay, sample.az,
                        sample.gx, sample.gy, sample.gz);
        } else {
            set_state(STATE_ERROR);
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

    while (true) {
        device_state_t state = get_state();
        if (state != last_state || s_mpu_ready != last_mpu || s_mock_enabled != last_mock ||
            s_sample_rate_hz != last_rate || s_duration_seconds != last_duration ||
            s_display_revision != last_revision || s_display_view != last_view ||
            s_developer_page != last_page) {
            display_render_current();
            last_state = state;
            last_mpu = s_mpu_ready;
            last_mock = s_mock_enabled;
            last_rate = s_sample_rate_hz;
            last_duration = s_duration_seconds;
            last_revision = s_display_revision;
            last_view = s_display_view;
            last_page = s_developer_page;
        }
        vTaskDelay(pdMS_TO_TICKS(100));
    }
}

static void handle_button_press(gpio_num_t pin)
{
    device_state_t state = get_state();
    display_request_refresh();

    if (state == STATE_RECORDING) {
        if (pin == PIN_BUTTON_OK) {
            stop_recording(false);
        } else if (pin == PIN_BUTTON_BACK) {
            stop_recording(true);
        }
        return;
    }

    if (s_display_view == DISPLAY_VIEW_SETTINGS) {
        if (pin == PIN_BUTTON_OK || pin == PIN_BUTTON_RIGHT) {
            s_display_view = DISPLAY_VIEW_DEVELOPER;
            s_developer_page = 0;
            serial_emit("UI,DEVELOPER,PAGE=1");
        } else if (pin == PIN_BUTTON_BACK || pin == PIN_BUTTON_LEFT) {
            s_display_view = DISPLAY_VIEW_STATUS;
            serial_emit("UI,HOME");
        }
        return;
    }

    if (s_display_view == DISPLAY_VIEW_DEVELOPER) {
        if (pin == PIN_BUTTON_BACK) {
            s_display_view = DISPLAY_VIEW_SETTINGS;
            serial_emit("UI,SETTINGS");
        } else if (pin == PIN_BUTTON_LEFT || pin == PIN_BUTTON_UP) {
            s_developer_page = s_developer_page == 0 ? 3 : s_developer_page - 1;
            serial_emit("UI,DEVELOPER,PAGE=%u", (unsigned)(s_developer_page + 1));
        } else if (pin == PIN_BUTTON_RIGHT || pin == PIN_BUTTON_DOWN) {
            s_developer_page = (uint8_t)((s_developer_page + 1) % 4);
            serial_emit("UI,DEVELOPER,PAGE=%u", (unsigned)(s_developer_page + 1));
        } else if (pin == PIN_BUTTON_OK && s_developer_page == 3) {
            s_display_view = DISPLAY_VIEW_COLOR_TEST;
            serial_emit("UI,COLOR_TEST");
        }
        return;
    }

    if (s_display_view == DISPLAY_VIEW_COLOR_TEST) {
        if (pin == PIN_BUTTON_OK || pin == PIN_BUTTON_BACK || pin == PIN_BUTTON_LEFT) {
            s_display_view = DISPLAY_VIEW_DEVELOPER;
            s_developer_page = 3;
            serial_emit("UI,DEVELOPER,PAGE=4");
        }
        return;
    }

    if (s_display_view == DISPLAY_VIEW_WALLPAPER) {
        if (pin == PIN_BUTTON_BACK || pin == PIN_BUTTON_OK) {
            s_display_view = DISPLAY_VIEW_STATUS;
            serial_emit("UI,HOME");
        }
        return;
    }

    if (pin == PIN_BUTTON_OK) {
        start_recording(s_sample_rate_hz, s_duration_seconds);
    } else if (pin == PIN_BUTTON_BACK) {
        s_display_view = DISPLAY_VIEW_SETTINGS;
        serial_emit("UI,SETTINGS");
    } else {
        if (pin == PIN_BUTTON_UP && s_duration_seconds < MAX_DURATION_SECONDS - 5U) {
            s_duration_seconds += 5U;
        } else if (pin == PIN_BUTTON_DOWN && s_duration_seconds > 5U) {
            s_duration_seconds -= 5U;
        } else if (pin == PIN_BUTTON_LEFT) {
            s_sample_rate_hz = s_sample_rate_hz <= 100U ? 50U : s_sample_rate_hz / 2U;
        } else if (pin == PIN_BUTTON_RIGHT) {
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
        case DISPLAY_VIEW_STATUS:
        default: return "home";
    }
}

void labcapsule_build_status_json(char *buffer, size_t buffer_size)
{
    if (!buffer || buffer_size == 0) {
        return;
    }
    snprintf(buffer, buffer_size,
             "{\"version\":\"%s\",\"state\":\"%s\",\"view\":\"%s\","
             "\"mpu\":\"%s\",\"mock\":%s,\"rate\":%lu,\"duration\":%lu,"
             "\"samples\":%lu,\"backlight\":%s,\"brightness\":%u,\"wallpaper\":%s,"
             "\"style\":{\"preset\":%u,\"wallpaperOpacity\":%u,"
             "\"panelOpacity\":%u,\"hudOpacity\":%u}}",
             LABCAPSULE_VERSION, state_name(get_state()), display_view_name(s_display_view),
             s_mpu_ready ? "ok" : "missing", s_mock_enabled ? "true" : "false",
             (unsigned long)s_sample_rate_hz, (unsigned long)s_duration_seconds,
             (unsigned long)s_sample_count, s_backlight_commanded_on ? "true" : "false",
             (unsigned)s_backlight_brightness, wallpaper_available() ? "true" : "false",
             (unsigned)s_visual_preset, (unsigned)s_wallpaper_opacity,
             (unsigned)s_panel_opacity, (unsigned)s_hud_opacity);
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
    s_display_view = DISPLAY_VIEW_MEDIA;
    s_media_frame_duration_ms = duration_ms < 20 ? 20 : duration_ms;
    s_live_background_override = s_media_canvas;
    display_render_state(get_state());
    s_live_background_override = NULL;
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

esp_err_t labcapsule_remote_action(const char *action, char *response, size_t response_size)
{
    if (!action || !response || response_size == 0) {
        return ESP_ERR_INVALID_ARG;
    }
    char normalized[48];
    size_t index = 0;
    while (action[index] && index < sizeof(normalized) - 1) {
        char value = action[index];
        normalized[index] = value == '-' ? '_' : (char)toupper((unsigned char)value);
        ++index;
    }
    normalized[index] = '\0';

    if (strncmp(normalized, "STYLE:", 6) == 0) {
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
    } else if (strcmp(normalized, "HOME") == 0 || strcmp(normalized, "STATUS") == 0) {
        s_display_view = DISPLAY_VIEW_STATUS;
    } else if (strcmp(normalized, "SETTINGS") == 0) {
        s_display_view = DISPLAY_VIEW_SETTINGS;
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
        gpio_num_t virtual_button = GPIO_NUM_NC;
        if (strcmp(normalized, "UP") == 0) virtual_button = PIN_BUTTON_UP;
        else if (strcmp(normalized, "DOWN") == 0) virtual_button = PIN_BUTTON_DOWN;
        else if (strcmp(normalized, "LEFT") == 0) virtual_button = PIN_BUTTON_LEFT;
        else if (strcmp(normalized, "RIGHT") == 0) virtual_button = PIN_BUTTON_RIGHT;
        else if (strcmp(normalized, "OK") == 0) virtual_button = PIN_BUTTON_OK;
        else if (strcmp(normalized, "BACK") == 0) virtual_button = PIN_BUTTON_BACK;
        if (virtual_button == GPIO_NUM_NC) {
            snprintf(response, response_size, "unknown action");
            return ESP_ERR_NOT_SUPPORTED;
        }
        handle_button_press(virtual_button);
    }
    display_request_refresh();
    snprintf(response, response_size, "applied");
    serial_emit("REMOTE,%s", normalized);
    return ESP_OK;
}

static void button_task(void *argument)
{
    (void)argument;
    const gpio_num_t pins[] = {
        PIN_BUTTON_UP, PIN_BUTTON_DOWN, PIN_BUTTON_LEFT,
        PIN_BUTTON_RIGHT, PIN_BUTTON_OK, PIN_BUTTON_BACK,
    };
    bool stable_pressed[sizeof(pins) / sizeof(pins[0])] = {false};
    bool sampled_pressed[sizeof(pins) / sizeof(pins[0])] = {false};
    uint8_t stable_counts[sizeof(pins) / sizeof(pins[0])] = {0};

    while (true) {
        for (size_t i = 0; i < sizeof(pins) / sizeof(pins[0]); ++i) {
            bool pressed = gpio_get_level(pins[i]) == 0;
            if (pressed == sampled_pressed[i]) {
                if (stable_counts[i] < 3) {
                    ++stable_counts[i];
                }
            } else {
                sampled_pressed[i] = pressed;
                stable_counts[i] = 0;
            }
            if (stable_counts[i] >= 3 && stable_pressed[i] != sampled_pressed[i]) {
                stable_pressed[i] = sampled_pressed[i];
                if (stable_pressed[i]) {
                    handle_button_press(pins[i]);
                }
            }
        }
        vTaskDelay(pdMS_TO_TICKS(10));
    }
}

void app_main(void)
{
    esp_log_level_set("*", ESP_LOG_INFO);

    ESP_ERROR_CHECK(serial_init());
    serial_emit("BOOT,LABCAPSULE,%s", LABCAPSULE_VERSION);
    serial_emit("PINOUT,I2C=8/9,TFT=12/11/10/7/6/5,BUTTONS=14/15/16/17/18/13");

    ESP_ERROR_CHECK(buttons_init());

    esp_err_t wallpaper_result = wallpaper_init();
    if (wallpaper_result != ESP_OK) {
        ESP_LOGW(TAG, "Wallpaper storage unavailable: %s", esp_err_to_name(wallpaper_result));
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
    ESP_ERROR_CHECK(sensor_hub_init(s_i2c_bus));
    sensor_hub_set_primary_ready("mpu6050", s_mpu_ready);

    set_state(STATE_READY);
    display_render_state(STATE_READY);

    xTaskCreate(serial_task, "serial_commands", 4096, NULL, 8, NULL);
    xTaskCreate(sampling_task, "motion_sampling", 4096, NULL, 9, NULL);
    xTaskCreate(display_task, "display_state", 4096, NULL, 4, NULL);
    xTaskCreate(button_task, "buttons", 3072, NULL, 5, NULL);

    esp_err_t connectivity_result = connectivity_start();
    if (connectivity_result == ESP_OK) {
        serial_emit("OK,CONNECTIVITY,WIFI=192.168.4.1,BLE=READY");
    } else {
        ESP_LOGE(TAG, "Connectivity unavailable: %s", esp_err_to_name(connectivity_result));
        serial_emit("WARN,CONNECTIVITY_FAILED,%s", esp_err_to_name(connectivity_result));
    }

    serial_emit("READY,TYPE=PING_OR_HELP");
    emit_status();
    emit_display_diagnostics();
}
