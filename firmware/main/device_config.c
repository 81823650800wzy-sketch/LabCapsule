#include "device_config.h"

#include <stdio.h>
#include <string.h>

#include "esp_check.h"
#include "nvs.h"

#define CONFIG_NAMESPACE "labcapsule"

static labcapsule_config_t s_config;

static void load_string(nvs_handle_t handle, const char *key, char *value, size_t capacity)
{
    size_t length = capacity;
    if (nvs_get_str(handle, key, value, &length) != ESP_OK) {
        value[0] = '\0';
    }
}

esp_err_t device_config_init(void)
{
    memset(&s_config, 0, sizeof(s_config));
    strlcpy(s_config.locale, "zh-CN", sizeof(s_config.locale));
    strlcpy(s_config.mqtt_topic, "labcapsule", sizeof(s_config.mqtt_topic));
    s_config.brightness = 90;
    s_config.visual_preset = 0;
    s_config.wallpaper_opacity = 82;
    s_config.panel_opacity = 76;
    s_config.hud_opacity = 100;
    s_config.keep_recovery_ap = true;

    nvs_handle_t handle;
    esp_err_t result = nvs_open(CONFIG_NAMESPACE, NVS_READONLY, &handle);
    if (result == ESP_ERR_NVS_NOT_FOUND) {
        return ESP_OK;
    }
    ESP_RETURN_ON_ERROR(result, "DeviceConfig", "NVS open failed");
    load_string(handle, "wifi_ssid", s_config.wifi_ssid, sizeof(s_config.wifi_ssid));
    load_string(handle, "wifi_pass", s_config.wifi_password, sizeof(s_config.wifi_password));
    load_string(handle, "mqtt_uri", s_config.mqtt_uri, sizeof(s_config.mqtt_uri));
    load_string(handle, "mqtt_user", s_config.mqtt_username, sizeof(s_config.mqtt_username));
    load_string(handle, "mqtt_pass", s_config.mqtt_password, sizeof(s_config.mqtt_password));
    load_string(handle, "mqtt_topic", s_config.mqtt_topic, sizeof(s_config.mqtt_topic));
    load_string(handle, "locale", s_config.locale, sizeof(s_config.locale));
    uint8_t value = 0;
    if (nvs_get_u8(handle, "brightness", &value) == ESP_OK) s_config.brightness = value;
    if (nvs_get_u8(handle, "ui_preset", &value) == ESP_OK) s_config.visual_preset = value;
    if (nvs_get_u8(handle, "wall_alpha", &value) == ESP_OK) s_config.wallpaper_opacity = value;
    if (nvs_get_u8(handle, "panel_alpha", &value) == ESP_OK) s_config.panel_opacity = value;
    if (nvs_get_u8(handle, "hud_alpha", &value) == ESP_OK) s_config.hud_opacity = value;
    if (nvs_get_u8(handle, "keep_ap", &value) == ESP_OK) s_config.keep_recovery_ap = value != 0;
    if (nvs_get_u8(handle, "remote", &value) == ESP_OK) s_config.remote_enabled = value != 0;
    nvs_close(handle);
    if (s_config.brightness > 100) s_config.brightness = 90;
    if (s_config.visual_preset > 2) s_config.visual_preset = 0;
    if (s_config.wallpaper_opacity > 100) s_config.wallpaper_opacity = 82;
    if (s_config.panel_opacity > 100) s_config.panel_opacity = 76;
    if (s_config.hud_opacity > 100) s_config.hud_opacity = 100;
    return ESP_OK;
}

const labcapsule_config_t *device_config_get(void)
{
    return &s_config;
}

esp_err_t device_config_save(const labcapsule_config_t *config)
{
    if (!config || config->brightness > 100 || config->visual_preset > 2 ||
        config->wallpaper_opacity > 100 || config->panel_opacity > 100 ||
        config->hud_opacity > 100) return ESP_ERR_INVALID_ARG;
    nvs_handle_t handle;
    ESP_RETURN_ON_ERROR(nvs_open(CONFIG_NAMESPACE, NVS_READWRITE, &handle),
                        "DeviceConfig", "NVS open failed");
    esp_err_t result = nvs_set_str(handle, "wifi_ssid", config->wifi_ssid);
    if (result == ESP_OK) result = nvs_set_str(handle, "wifi_pass", config->wifi_password);
    if (result == ESP_OK) result = nvs_set_str(handle, "mqtt_uri", config->mqtt_uri);
    if (result == ESP_OK) result = nvs_set_str(handle, "mqtt_user", config->mqtt_username);
    if (result == ESP_OK) result = nvs_set_str(handle, "mqtt_pass", config->mqtt_password);
    if (result == ESP_OK) result = nvs_set_str(handle, "mqtt_topic", config->mqtt_topic);
    if (result == ESP_OK) result = nvs_set_str(handle, "locale", config->locale);
    if (result == ESP_OK) result = nvs_set_u8(handle, "brightness", config->brightness);
    if (result == ESP_OK) result = nvs_set_u8(handle, "ui_preset", config->visual_preset);
    if (result == ESP_OK) result = nvs_set_u8(handle, "wall_alpha", config->wallpaper_opacity);
    if (result == ESP_OK) result = nvs_set_u8(handle, "panel_alpha", config->panel_opacity);
    if (result == ESP_OK) result = nvs_set_u8(handle, "hud_alpha", config->hud_opacity);
    if (result == ESP_OK) result = nvs_set_u8(handle, "keep_ap", config->keep_recovery_ap);
    if (result == ESP_OK) result = nvs_set_u8(handle, "remote", config->remote_enabled);
    if (result == ESP_OK) result = nvs_commit(handle);
    nvs_close(handle);
    if (result == ESP_OK) s_config = *config;
    return result;
}

void device_config_redacted_json(char *buffer, size_t buffer_size)
{
    if (!buffer || buffer_size == 0) return;
    snprintf(buffer, buffer_size,
             "{\"wifiSsid\":\"%s\",\"wifiConfigured\":%s,\"mqttUri\":\"%s\","
             "\"mqttUser\":\"%s\",\"mqttTopic\":\"%s\",\"remoteEnabled\":%s,"
             "\"keepRecoveryAp\":%s,\"locale\":\"%s\",\"brightness\":%u,"
             "\"visualPreset\":%u,\"wallpaperOpacity\":%u,"
             "\"panelOpacity\":%u,\"hudOpacity\":%u}",
             s_config.wifi_ssid, s_config.wifi_ssid[0] ? "true" : "false",
             s_config.mqtt_uri, s_config.mqtt_username, s_config.mqtt_topic,
             s_config.remote_enabled ? "true" : "false",
             s_config.keep_recovery_ap ? "true" : "false",
             s_config.locale, (unsigned)s_config.brightness,
             (unsigned)s_config.visual_preset, (unsigned)s_config.wallpaper_opacity,
             (unsigned)s_config.panel_opacity, (unsigned)s_config.hud_opacity);
}
