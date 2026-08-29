#include "wallpaper.h"

#include <string.h>

#include "esp_check.h"
#include "esp_log.h"
#include "esp_partition.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define WALLPAPER_PARTITION_LABEL "wallpaper"
#define WALLPAPER_MAGIC 0x4C435750U
#define WALLPAPER_FORMAT_VERSION 1U
#define WALLPAPER_DATA_OFFSET 0x1000U
#define WALLPAPER_ROWS_PER_BLOCK 8U

typedef struct {
    uint32_t magic;
    uint16_t format_version;
    uint16_t width;
    uint16_t height;
    uint16_t reserved;
    uint32_t payload_size;
    uint32_t generation;
} wallpaper_header_t;

static const char *TAG = "Wallpaper";
static const esp_partition_t *s_partition;
static size_t s_received;
static bool s_upload_active;
static uint32_t s_generation;
static uint8_t s_draw_buffers[2][WALLPAPER_WIDTH * WALLPAPER_ROWS_PER_BLOCK * 2U];
static uint8_t s_draw_buffer_index;

static bool header_valid(const wallpaper_header_t *header)
{
    return header->magic == WALLPAPER_MAGIC &&
           header->format_version == WALLPAPER_FORMAT_VERSION &&
           header->width == WALLPAPER_WIDTH &&
           header->height == WALLPAPER_HEIGHT &&
           header->payload_size == WALLPAPER_PAYLOAD_BYTES;
}

esp_err_t wallpaper_init(void)
{
    s_partition = esp_partition_find_first(ESP_PARTITION_TYPE_DATA, 0x40,
                                           WALLPAPER_PARTITION_LABEL);
    if (!s_partition) {
        ESP_LOGE(TAG, "Partition '%s' not found", WALLPAPER_PARTITION_LABEL);
        return ESP_ERR_NOT_FOUND;
    }
    wallpaper_header_t header = {0};
    ESP_RETURN_ON_ERROR(esp_partition_read(s_partition, 0, &header, sizeof(header)), TAG,
                        "Header read failed");
    if (header_valid(&header)) {
        s_generation = header.generation;
        ESP_LOGI(TAG, "Wallpaper generation %lu ready", (unsigned long)s_generation);
    }
    return ESP_OK;
}

bool wallpaper_available(void)
{
    if (!s_partition) {
        return false;
    }
    wallpaper_header_t header = {0};
    return esp_partition_read(s_partition, 0, &header, sizeof(header)) == ESP_OK &&
           header_valid(&header);
}

esp_err_t wallpaper_clear(void)
{
    if (!s_partition) return ESP_ERR_INVALID_STATE;
    return esp_partition_erase_range(s_partition, 0, WALLPAPER_DATA_OFFSET);
}

esp_err_t wallpaper_upload_begin(size_t payload_size)
{
    if (!s_partition || payload_size != WALLPAPER_PAYLOAD_BYTES || s_upload_active) {
        return ESP_ERR_INVALID_STATE;
    }
    if (WALLPAPER_DATA_OFFSET + payload_size > s_partition->size) {
        return ESP_ERR_INVALID_SIZE;
    }
    ESP_RETURN_ON_ERROR(esp_partition_erase_range(s_partition, 0, s_partition->size), TAG,
                        "Partition erase failed");
    s_received = 0;
    s_upload_active = true;
    return ESP_OK;
}

esp_err_t wallpaper_upload_write(const uint8_t *data, size_t length)
{
    if (!s_upload_active || !data || length == 0 ||
        s_received + length > WALLPAPER_PAYLOAD_BYTES) {
        return ESP_ERR_INVALID_ARG;
    }
    ESP_RETURN_ON_ERROR(esp_partition_write(s_partition,
                                             WALLPAPER_DATA_OFFSET + s_received,
                                             data, length), TAG,
                        "Payload write failed");
    s_received += length;
    return ESP_OK;
}

esp_err_t wallpaper_upload_finish(void)
{
    if (!s_upload_active || s_received != WALLPAPER_PAYLOAD_BYTES) {
        wallpaper_upload_abort();
        return ESP_ERR_INVALID_SIZE;
    }
    wallpaper_header_t header = {
        .magic = WALLPAPER_MAGIC,
        .format_version = WALLPAPER_FORMAT_VERSION,
        .width = WALLPAPER_WIDTH,
        .height = WALLPAPER_HEIGHT,
        .payload_size = WALLPAPER_PAYLOAD_BYTES,
        .generation = ++s_generation,
    };
    esp_err_t result = esp_partition_write(s_partition, 0, &header, sizeof(header));
    s_upload_active = false;
    if (result == ESP_OK) {
        ESP_LOGI(TAG, "Wallpaper upload complete (%u bytes)", WALLPAPER_PAYLOAD_BYTES);
    }
    return result;
}

void wallpaper_upload_abort(void)
{
    s_upload_active = false;
    s_received = 0;
}

size_t wallpaper_upload_received(void)
{
    return s_received;
}

esp_err_t wallpaper_draw(esp_lcd_panel_handle_t panel)
{
    if (!panel || !wallpaper_available()) {
        return ESP_ERR_NOT_FOUND;
    }
    const size_t row_bytes = WALLPAPER_WIDTH * 2U;
    for (size_t y = 0; y < WALLPAPER_HEIGHT; y += WALLPAPER_ROWS_PER_BLOCK) {
        uint8_t *draw_buffer = s_draw_buffers[s_draw_buffer_index];
        size_t rows = WALLPAPER_ROWS_PER_BLOCK;
        if (y + rows > WALLPAPER_HEIGHT) {
            rows = WALLPAPER_HEIGHT - y;
        }
        size_t bytes = rows * row_bytes;
        ESP_RETURN_ON_ERROR(esp_partition_read(s_partition,
                                                WALLPAPER_DATA_OFFSET + y * row_bytes,
                                                draw_buffer, bytes), TAG,
                            "Wallpaper read failed");
        ESP_RETURN_ON_ERROR(esp_lcd_panel_draw_bitmap(panel, 0, (int)y,
                                                       WALLPAPER_WIDTH, (int)(y + rows),
                                                       draw_buffer), TAG,
                            "Wallpaper draw failed");
        s_draw_buffer_index ^= 1U;
    }
    // Keep the persistent draw buffer untouched until the final queued SPI transfer completes.
    vTaskDelay(pdMS_TO_TICKS(20));
    return ESP_OK;
}

esp_err_t wallpaper_read_frame(void *rgb565, size_t capacity)
{
    if (!rgb565 || capacity < WALLPAPER_PAYLOAD_BYTES || !wallpaper_available()) {
        return ESP_ERR_INVALID_ARG;
    }
    return esp_partition_read(s_partition, WALLPAPER_DATA_OFFSET, rgb565,
                              WALLPAPER_PAYLOAD_BYTES);
}
