#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"

typedef struct {
    char wifi_ssid[33];
    char wifi_password[65];
    char mqtt_uri[129];
    char mqtt_username[65];
    char mqtt_password[65];
    char mqtt_topic[65];
    char locale[8];
    uint8_t brightness;
    uint8_t visual_preset;
    uint8_t wallpaper_opacity;
    uint8_t panel_opacity;
    uint8_t hud_opacity;
    bool keep_recovery_ap;
    bool remote_enabled;
} labcapsule_config_t;

esp_err_t device_config_init(void);
const labcapsule_config_t *device_config_get(void);
esp_err_t device_config_save(const labcapsule_config_t *config);
void device_config_redacted_json(char *buffer, size_t buffer_size);
