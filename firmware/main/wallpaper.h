#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"
#include "esp_lcd_panel_ops.h"

#define WALLPAPER_WIDTH 240U
#define WALLPAPER_HEIGHT 320U
#define WALLPAPER_PAYLOAD_BYTES (WALLPAPER_WIDTH * WALLPAPER_HEIGHT * 2U)

esp_err_t wallpaper_init(void);
bool wallpaper_available(void);
esp_err_t wallpaper_upload_begin(size_t payload_size);
esp_err_t wallpaper_upload_write(const uint8_t *data, size_t length);
esp_err_t wallpaper_upload_finish(void);
void wallpaper_upload_abort(void);
size_t wallpaper_upload_received(void);
esp_err_t wallpaper_draw(esp_lcd_panel_handle_t panel);
esp_err_t wallpaper_read_frame(void *rgb565, size_t capacity);
