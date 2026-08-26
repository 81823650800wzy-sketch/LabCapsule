#include "connectivity.h"

#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "device_config.h"
#include "esp_check.h"
#include "esp_crt_bundle.h"
#include "esp_event.h"
#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_ota_ops.h"
#include "esp_system.h"
#include "esp_wifi.h"
#include "cJSON.h"
#include "esp_netif_ip_addr.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "host/ble_att.h"
#include "host/ble_gap.h"
#include "host/ble_gatt.h"
#include "host/ble_hs.h"
#include "host/util/util.h"
#include "host/ble_uuid.h"
#include "labcapsule_control.h"
#include "mqtt_client.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "nvs_flash.h"
#include "os/os_mbuf.h"
#include "services/gap/ble_svc_gap.h"
#include "services/gatt/ble_svc_gatt.h"
#include "sensor_hub.h"
#include "wallpaper.h"

#define WIFI_AP_PASSWORD "labcapsule"
#define HTTP_BUFFER_SIZE 4096U
#define BLE_VALUE_MAX 512U
#define MEDIA_CONTROL_MAX 128U

static const char *TAG = "Connectivity";
static char s_device_name[24] = "LabCapsule";
static char s_ap_ssid[24] = "LabCapsule";
static uint8_t s_ble_own_addr_type;
static uint16_t s_ble_status_handle;
static bool s_sta_connected;
static bool s_remote_connected;
static char s_sta_ip[16] = "0.0.0.0";
static esp_mqtt_client_handle_t s_mqtt_client;
static char s_mqtt_command_topic[160];
static char s_mqtt_status_topic[160];

static bool s_ota_active;
static esp_ota_handle_t s_ota_handle;
static const esp_partition_t *s_ota_partition;
static size_t s_ota_expected;
static size_t s_ota_received;

typedef enum {
    FILE_TRANSFER_NONE,
    FILE_TRANSFER_FRAME,
    FILE_TRANSFER_WALLPAPER,
} file_transfer_kind_t;

static file_transfer_kind_t s_file_kind;
static size_t s_file_expected;
static size_t s_file_received;
static uint32_t s_file_crc_expected;
static uint32_t s_file_crc;
static uint32_t s_file_duration_ms;

/* 6c430001-4c61-6243-6170-73756c650001 */
static const ble_uuid128_t s_service_uuid = BLE_UUID128_INIT(
    0x01, 0x00, 0x65, 0x6c, 0x75, 0x73, 0x70, 0x61,
    0x43, 0x62, 0x61, 0x4c, 0x01, 0x00, 0x43, 0x6c);
/* 6c430002-4c61-6243-6170-73756c650001 */
static const ble_uuid128_t s_command_uuid = BLE_UUID128_INIT(
    0x01, 0x00, 0x65, 0x6c, 0x75, 0x73, 0x70, 0x61,
    0x43, 0x62, 0x61, 0x4c, 0x02, 0x00, 0x43, 0x6c);
/* 6c430003-4c61-6243-6170-73756c650001 */
static const ble_uuid128_t s_status_uuid = BLE_UUID128_INIT(
    0x01, 0x00, 0x65, 0x6c, 0x75, 0x73, 0x70, 0x61,
    0x43, 0x62, 0x61, 0x4c, 0x03, 0x00, 0x43, 0x6c);
/* 6c430004-4c61-6243-6170-73756c650001 */
static const ble_uuid128_t s_ota_control_uuid = BLE_UUID128_INIT(
    0x01, 0x00, 0x65, 0x6c, 0x75, 0x73, 0x70, 0x61,
    0x43, 0x62, 0x61, 0x4c, 0x04, 0x00, 0x43, 0x6c);
/* 6c430005-4c61-6243-6170-73756c650001 */
static const ble_uuid128_t s_ota_data_uuid = BLE_UUID128_INIT(
    0x01, 0x00, 0x65, 0x6c, 0x75, 0x73, 0x70, 0x61,
    0x43, 0x62, 0x61, 0x4c, 0x05, 0x00, 0x43, 0x6c);
/* General media/file control and data characteristics. */
static const ble_uuid128_t s_file_control_uuid = BLE_UUID128_INIT(
    0x01, 0x00, 0x65, 0x6c, 0x75, 0x73, 0x70, 0x61,
    0x43, 0x62, 0x61, 0x4c, 0x06, 0x00, 0x43, 0x6c);
static const ble_uuid128_t s_file_data_uuid = BLE_UUID128_INIT(
    0x01, 0x00, 0x65, 0x6c, 0x75, 0x73, 0x70, 0x61,
    0x43, 0x62, 0x61, 0x4c, 0x07, 0x00, 0x43, 0x6c);

static uint32_t crc32_update(uint32_t crc, const uint8_t *data, size_t length)
{
    crc = ~crc;
    for (size_t i = 0; i < length; ++i) {
        crc ^= data[i];
        for (unsigned bit = 0; bit < 8; ++bit) {
            crc = (crc >> 1) ^ (0xEDB88320U & (uint32_t)-(int32_t)(crc & 1U));
        }
    }
    return ~crc;
}

static void file_transfer_abort(void)
{
    if (s_file_kind == FILE_TRANSFER_FRAME) labcapsule_media_frame_abort();
    if (s_file_kind == FILE_TRANSFER_WALLPAPER) wallpaper_upload_abort();
    s_file_kind = FILE_TRANSFER_NONE;
    s_file_expected = s_file_received = 0;
    s_file_crc = s_file_crc_expected = 0;
}

static esp_err_t file_transfer_begin(file_transfer_kind_t kind, size_t size,
                                     uint32_t duration_ms, uint32_t crc,
                                     labcapsule_media_encoding_t encoding,
                                     uint16_t x, uint16_t y, uint16_t width,
                                     uint16_t height)
{
    if (s_file_kind != FILE_TRANSFER_NONE || size == 0 ||
        size > WALLPAPER_PAYLOAD_BYTES ||
        (kind == FILE_TRANSFER_WALLPAPER && size != WALLPAPER_PAYLOAD_BYTES)) {
        return ESP_ERR_INVALID_STATE;
    }
    esp_err_t result = kind == FILE_TRANSFER_FRAME
        ? labcapsule_media_region_begin(size, x, y, width, height, encoding)
        : wallpaper_upload_begin(size);
    if (result != ESP_OK) return result;
    s_file_kind = kind;
    s_file_expected = size;
    s_file_received = 0;
    s_file_crc = 0;
    s_file_crc_expected = crc;
    s_file_duration_ms = duration_ms;
    return ESP_OK;
}

static esp_err_t file_transfer_write(const uint8_t *data, size_t length)
{
    if (s_file_kind == FILE_TRANSFER_NONE || !data || length == 0 ||
        s_file_received + length > s_file_expected) return ESP_ERR_INVALID_ARG;
    esp_err_t result = s_file_kind == FILE_TRANSFER_FRAME
        ? labcapsule_media_frame_write(data, length) : wallpaper_upload_write(data, length);
    if (result == ESP_OK) {
        s_file_crc = crc32_update(s_file_crc, data, length);
        s_file_received += length;
    }
    return result;
}

static esp_err_t file_transfer_finish(void)
{
    if (s_file_kind == FILE_TRANSFER_NONE || s_file_received != s_file_expected ||
        (s_file_crc_expected != 0 && s_file_crc != s_file_crc_expected)) {
        file_transfer_abort();
        return ESP_ERR_INVALID_CRC;
    }
    esp_err_t result = s_file_kind == FILE_TRANSFER_FRAME
        ? labcapsule_media_frame_finish(s_file_duration_ms) : wallpaper_upload_finish();
    file_transfer_kind_t completed = s_file_kind;
    s_file_kind = FILE_TRANSFER_NONE;
    s_file_expected = s_file_received = 0;
    if (result == ESP_OK && completed == FILE_TRANSFER_WALLPAPER) labcapsule_show_wallpaper();
    return result;
}

static void restart_task(void *argument)
{
    (void)argument;
    vTaskDelay(pdMS_TO_TICKS(1200));
    esp_restart();
}

static void schedule_restart(void)
{
    xTaskCreate(restart_task, "ota_restart", 2048, NULL, 10, NULL);
}

static esp_err_t ota_begin(size_t expected_size)
{
    if (s_ota_active || expected_size == 0) {
        return ESP_ERR_INVALID_STATE;
    }
    s_ota_partition = esp_ota_get_next_update_partition(NULL);
    if (!s_ota_partition || expected_size > s_ota_partition->size) {
        return ESP_ERR_INVALID_SIZE;
    }
    esp_err_t result = esp_ota_begin(s_ota_partition, expected_size, &s_ota_handle);
    if (result != ESP_OK) {
        return result;
    }
    s_ota_expected = expected_size;
    s_ota_received = 0;
    s_ota_active = true;
    ESP_LOGI(TAG, "OTA begin: %u bytes -> %s", (unsigned)expected_size,
             s_ota_partition->label);
    return ESP_OK;
}

static esp_err_t ota_write(const uint8_t *data, size_t length)
{
    if (!s_ota_active || !data || length == 0 ||
        s_ota_received + length > s_ota_expected) {
        return ESP_ERR_INVALID_ARG;
    }
    ESP_RETURN_ON_ERROR(esp_ota_write(s_ota_handle, data, length), TAG,
                        "OTA write failed");
    s_ota_received += length;
    return ESP_OK;
}

static void ota_abort(void)
{
    if (s_ota_active) {
        esp_ota_abort(s_ota_handle);
    }
    s_ota_active = false;
    s_ota_expected = 0;
    s_ota_received = 0;
}

static esp_err_t ota_finish(void)
{
    if (!s_ota_active || s_ota_received != s_ota_expected) {
        ota_abort();
        return ESP_ERR_INVALID_SIZE;
    }
    esp_err_t result = esp_ota_end(s_ota_handle);
    s_ota_active = false;
    if (result != ESP_OK) {
        return result;
    }
    ESP_RETURN_ON_ERROR(esp_ota_set_boot_partition(s_ota_partition), TAG,
                        "OTA boot partition selection failed");
    ESP_LOGI(TAG, "OTA verified; reboot scheduled");
    return ESP_OK;
}

static void http_common_headers(httpd_req_t *request)
{
    httpd_resp_set_type(request, "application/json; charset=utf-8");
    httpd_resp_set_hdr(request, "Access-Control-Allow-Origin", "*");
    httpd_resp_set_hdr(request, "Access-Control-Allow-Headers", "Content-Type");
    httpd_resp_set_hdr(request, "Access-Control-Allow-Methods", "GET,POST,OPTIONS");
    httpd_resp_set_hdr(request, "Cache-Control", "no-store");
}

static esp_err_t http_json(httpd_req_t *request, const char *status,
                           const char *json)
{
    http_common_headers(request);
    if (status) {
        httpd_resp_set_status(request, status);
    }
    return httpd_resp_sendstr(request, json);
}

static int hex_value(char value)
{
    if (value >= '0' && value <= '9') return value - '0';
    if (value >= 'a' && value <= 'f') return value - 'a' + 10;
    if (value >= 'A' && value <= 'F') return value - 'A' + 10;
    return -1;
}

static void url_decode(char *value)
{
    char *read = value;
    char *write = value;
    while (*read) {
        if (*read == '+' ) {
            *write++ = ' ';
            ++read;
        } else if (*read == '%' && read[1] && read[2] &&
                   hex_value(read[1]) >= 0 && hex_value(read[2]) >= 0) {
            *write++ = (char)((hex_value(read[1]) << 4) | hex_value(read[2]));
            read += 3;
        } else {
            *write++ = *read++;
        }
    }
    *write = '\0';
}

static bool query_value(const char *query, const char *key, char *value, size_t capacity)
{
    if (!query || httpd_query_key_value(query, key, value, capacity) != ESP_OK) return false;
    url_decode(value);
    return true;
}

static void mqtt_restart(void);

static esp_err_t wifi_station_apply(void)
{
    const labcapsule_config_t *saved = device_config_get();
    wifi_config_t station = {0};
    strlcpy((char *)station.sta.ssid, saved->wifi_ssid, sizeof(station.sta.ssid));
    strlcpy((char *)station.sta.password, saved->wifi_password, sizeof(station.sta.password));
    station.sta.threshold.authmode = saved->wifi_password[0]
            ? WIFI_AUTH_WPA2_PSK : WIFI_AUTH_OPEN;
    station.sta.pmf_cfg.capable = true;
    station.sta.pmf_cfg.required = false;
    ESP_RETURN_ON_ERROR(esp_wifi_set_config(WIFI_IF_STA, &station), TAG,
                        "Wi-Fi station config failed");
    if (saved->wifi_ssid[0]) {
        esp_wifi_disconnect();
        return esp_wifi_connect();
    }
    return ESP_OK;
}

void connectivity_build_status_json(char *buffer, size_t buffer_size)
{
    if (!buffer || buffer_size == 0) return;
    const labcapsule_config_t *config = device_config_get();
    snprintf(buffer, buffer_size,
             "{\"mode\":\"ap+sta\",\"recoveryAp\":\"%s\",\"staConfigured\":%s,"
             "\"staConnected\":%s,\"staIp\":\"%s\",\"remoteEnabled\":%s,"
             "\"remoteConnected\":%s}",
             s_ap_ssid, config->wifi_ssid[0] ? "true" : "false",
             s_sta_connected ? "true" : "false", s_sta_ip,
             config->remote_enabled ? "true" : "false",
             s_remote_connected ? "true" : "false");
}

static esp_err_t status_handler(httpd_req_t *request)
{
    char device_status[384];
    char network_status[384];
    char response[900];
    labcapsule_build_status_json(device_status, sizeof(device_status));
    connectivity_build_status_json(network_status, sizeof(network_status));
    snprintf(response, sizeof(response),
             "{\"ok\":true,\"transport\":\"wifi\",\"ssid\":\"%s\","
             "\"device\":%s,\"network\":%s}", s_ap_ssid, device_status,
             network_status);
    return http_json(request, NULL, response);
}

static esp_err_t network_handler(httpd_req_t *request)
{
    if (request->method == HTTP_GET) {
        char config[640];
        char network[384];
        char response[1100];
        device_config_redacted_json(config, sizeof(config));
        connectivity_build_status_json(network, sizeof(network));
        snprintf(response, sizeof(response), "{\"ok\":true,\"config\":%s,\"network\":%s}",
                 config, network);
        return http_json(request, NULL, response);
    }

    if (request->content_len <= 0 || request->content_len >= 1024) {
        return http_json(request, "400 Bad Request",
                         "{\"ok\":false,\"error\":\"missing configuration\"}");
    }
    char body[1024];
    size_t received_total = 0;
    while (received_total < (size_t)request->content_len) {
        int received = httpd_req_recv(request, body + received_total,
                                      request->content_len - received_total);
        if (received == HTTPD_SOCK_ERR_TIMEOUT) continue;
        if (received <= 0) return ESP_FAIL;
        received_total += (size_t)received;
    }
    body[received_total] = '\0';
    cJSON *root = cJSON_Parse(body);
    if (!root) {
        return http_json(request, "400 Bad Request",
                         "{\"ok\":false,\"error\":\"invalid JSON\"}");
    }
    labcapsule_config_t config = *device_config_get();
    const cJSON *item = NULL;
#define COPY_JSON_STRING(key, destination) do { \
    item = cJSON_GetObjectItemCaseSensitive(root, key); \
    if (cJSON_IsString(item) && item->valuestring) \
        strlcpy(destination, item->valuestring, sizeof(destination)); \
} while (0)
    COPY_JSON_STRING("ssid", config.wifi_ssid);
    COPY_JSON_STRING("password", config.wifi_password);
    COPY_JSON_STRING("mqttUri", config.mqtt_uri);
    COPY_JSON_STRING("mqttUser", config.mqtt_username);
    COPY_JSON_STRING("mqttPassword", config.mqtt_password);
    COPY_JSON_STRING("mqttTopic", config.mqtt_topic);
    COPY_JSON_STRING("locale", config.locale);
#undef COPY_JSON_STRING
    item = cJSON_GetObjectItemCaseSensitive(root, "keepAp");
    if (cJSON_IsBool(item)) config.keep_recovery_ap = cJSON_IsTrue(item);
    item = cJSON_GetObjectItemCaseSensitive(root, "remote");
    if (cJSON_IsBool(item)) config.remote_enabled = cJSON_IsTrue(item);
    item = cJSON_GetObjectItemCaseSensitive(root, "brightness");
    if (cJSON_IsNumber(item)) {
        int brightness = item->valueint;
        config.brightness = (uint8_t)(brightness < 0 ? 0 : brightness > 100 ? 100 : brightness);
    }
    cJSON_Delete(root);
    if (device_config_save(&config) != ESP_OK || wifi_station_apply() != ESP_OK) {
        return http_json(request, "500 Internal Server Error",
                         "{\"ok\":false,\"error\":\"configuration failed\"}");
    }
    labcapsule_set_brightness(config.brightness);
    mqtt_restart();
    return http_json(request, NULL,
                     "{\"ok\":true,\"message\":\"saved; station connecting\"}");
}

static esp_err_t sensors_handler(httpd_req_t *request)
{
    char sensors[1600];
    char response[1700];
    sensor_hub_discover();
    sensor_hub_build_json(sensors, sizeof(sensors));
    snprintf(response, sizeof(response), "{\"ok\":true,\"hub\":%s}", sensors);
    return http_json(request, NULL, response);
}

static esp_err_t media_frame_handler(httpd_req_t *request)
{
    uint32_t duration = 100;
    unsigned x = 0;
    unsigned y = 0;
    unsigned width = 240;
    unsigned height = 320;
    labcapsule_media_encoding_t encoding = LABCAPSULE_MEDIA_RAW565;
    char query[192];
    char value[24];
    if (httpd_req_get_url_query_str(request, query, sizeof(query)) == ESP_OK) {
        if (query_value(query, "duration", value, sizeof(value)))
            duration = (uint32_t)strtoul(value, NULL, 10);
        if (query_value(query, "x", value, sizeof(value))) x = strtoul(value, NULL, 10);
        if (query_value(query, "y", value, sizeof(value))) y = strtoul(value, NULL, 10);
        if (query_value(query, "w", value, sizeof(value))) width = strtoul(value, NULL, 10);
        if (query_value(query, "h", value, sizeof(value))) height = strtoul(value, NULL, 10);
        if (query_value(query, "enc", value, sizeof(value))) {
            if (strcmp(value, "rle565") == 0) encoding = LABCAPSULE_MEDIA_RLE565;
            else if (strcmp(value, "rgb332") == 0) encoding = LABCAPSULE_MEDIA_RGB332;
            else if (strcmp(value, "rle332") == 0) encoding = LABCAPSULE_MEDIA_RLE332;
        }
    }
    if (request->content_len <= 0 || request->content_len > WALLPAPER_PAYLOAD_BYTES ||
        x > UINT16_MAX || y > UINT16_MAX || width > UINT16_MAX || height > UINT16_MAX ||
        labcapsule_media_region_begin(request->content_len, x, y, width, height,
                                      encoding) != ESP_OK) {
        return http_json(request, "409 Conflict",
                         "{\"ok\":false,\"error\":\"invalid media region\"}");
    }
    uint8_t *buffer = malloc(HTTP_BUFFER_SIZE);
    if (!buffer) {
        labcapsule_media_frame_abort();
        return http_json(request, "500 Internal Server Error",
                         "{\"ok\":false,\"error\":\"out of memory\"}");
    }
    size_t remaining = request->content_len;
    while (remaining > 0) {
        size_t wanted = remaining < HTTP_BUFFER_SIZE ? remaining : HTTP_BUFFER_SIZE;
        int received = httpd_req_recv(request, (char *)buffer, wanted);
        if (received == HTTPD_SOCK_ERR_TIMEOUT) continue;
        if (received <= 0 || labcapsule_media_frame_write(buffer, received) != ESP_OK) {
            free(buffer);
            labcapsule_media_frame_abort();
            return ESP_FAIL;
        }
        remaining -= (size_t)received;
    }
    free(buffer);
    if (labcapsule_media_frame_finish(duration) != ESP_OK) {
        return http_json(request, "500 Internal Server Error",
                         "{\"ok\":false,\"error\":\"frame rejected\"}");
    }
    char response[192];
    snprintf(response, sizeof(response),
             "{\"ok\":true,\"bytes\":%d,\"region\":\"%ux%u@%u,%u\",\"encoding\":%u}",
             request->content_len, width, height, x, y,
             (unsigned)encoding);
    return http_json(request, NULL, response);
}

static esp_err_t control_handler(httpd_req_t *request)
{
    char query[128];
    char action[48];
    char message[96];
    if (httpd_req_get_url_query_str(request, query, sizeof(query)) != ESP_OK ||
        httpd_query_key_value(query, "action", action, sizeof(action)) != ESP_OK) {
        return http_json(request, "400 Bad Request",
                         "{\"ok\":false,\"error\":\"missing action\"}");
    }
    esp_err_t result = labcapsule_remote_action(action, message, sizeof(message));
    if (result != ESP_OK) {
        char response[160];
        snprintf(response, sizeof(response),
                 "{\"ok\":false,\"error\":\"%s\"}", message);
        return http_json(request, "400 Bad Request", response);
    }
    char response[256];
    snprintf(response, sizeof(response),
             "{\"ok\":true,\"action\":\"%s\",\"message\":\"%s\"}",
             action, message);
    return http_json(request, NULL, response);
}

static esp_err_t experiment_handler(httpd_req_t *request)
{
    char query[128];
    char value[24];
    if (httpd_req_get_url_query_str(request, query, sizeof(query)) != ESP_OK) {
        return http_json(request, "400 Bad Request",
                         "{\"ok\":false,\"error\":\"missing protocol parameters\"}");
    }
    uint32_t rate = 0;
    uint32_t duration = 0;
    if (query_value(query, "rate", value, sizeof(value)))
        rate = (uint32_t)strtoul(value, NULL, 10);
    if (query_value(query, "duration", value, sizeof(value)))
        duration = (uint32_t)strtoul(value, NULL, 10);
    esp_err_t result = labcapsule_start_experiment(rate, duration);
    if (result != ESP_OK) {
        char response[160];
        snprintf(response, sizeof(response),
                 "{\"ok\":false,\"error\":\"experiment rejected\",\"code\":%d}",
                 (int)result);
        return http_json(request, "409 Conflict", response);
    }
    char response[160];
    snprintf(response, sizeof(response),
             "{\"ok\":true,\"sampleRateHz\":%lu,\"durationSeconds\":%lu}",
             (unsigned long)rate, (unsigned long)duration);
    return http_json(request, NULL, response);
}

static esp_err_t wallpaper_handler(httpd_req_t *request)
{
    if ((size_t)request->content_len != WALLPAPER_PAYLOAD_BYTES) {
        return http_json(request, "400 Bad Request",
                         "{\"ok\":false,\"error\":\"wallpaper must be 240x320 RGB565\"}");
    }
    esp_err_t result = wallpaper_upload_begin(request->content_len);
    if (result != ESP_OK) {
        return http_json(request, "409 Conflict",
                         "{\"ok\":false,\"error\":\"wallpaper upload busy\"}");
    }
    uint8_t *buffer = malloc(HTTP_BUFFER_SIZE);
    if (!buffer) {
        wallpaper_upload_abort();
        return http_json(request, "500 Internal Server Error",
                         "{\"ok\":false,\"error\":\"out of memory\"}");
    }
    size_t remaining = request->content_len;
    while (remaining > 0) {
        size_t wanted = remaining < HTTP_BUFFER_SIZE ? remaining : HTTP_BUFFER_SIZE;
        int received = httpd_req_recv(request, (char *)buffer, wanted);
        if (received == HTTPD_SOCK_ERR_TIMEOUT) {
            continue;
        }
        if (received <= 0 || wallpaper_upload_write(buffer, (size_t)received) != ESP_OK) {
            free(buffer);
            wallpaper_upload_abort();
            return ESP_FAIL;
        }
        remaining -= (size_t)received;
    }
    free(buffer);
    result = wallpaper_upload_finish();
    if (result != ESP_OK) {
        return http_json(request, "500 Internal Server Error",
                         "{\"ok\":false,\"error\":\"wallpaper validation failed\"}");
    }
    labcapsule_show_wallpaper();
    return http_json(request, NULL,
                     "{\"ok\":true,\"message\":\"wallpaper stored and displayed\"}");
}

static esp_err_t ota_handler(httpd_req_t *request)
{
    esp_err_t result = ota_begin(request->content_len);
    if (result != ESP_OK) {
        return http_json(request, "409 Conflict",
                         "{\"ok\":false,\"error\":\"OTA busy or image too large\"}");
    }
    uint8_t *buffer = malloc(HTTP_BUFFER_SIZE);
    if (!buffer) {
        ota_abort();
        return http_json(request, "500 Internal Server Error",
                         "{\"ok\":false,\"error\":\"out of memory\"}");
    }
    size_t remaining = request->content_len;
    while (remaining > 0) {
        size_t wanted = remaining < HTTP_BUFFER_SIZE ? remaining : HTTP_BUFFER_SIZE;
        int received = httpd_req_recv(request, (char *)buffer, wanted);
        if (received == HTTPD_SOCK_ERR_TIMEOUT) {
            continue;
        }
        if (received <= 0 || ota_write(buffer, (size_t)received) != ESP_OK) {
            free(buffer);
            ota_abort();
            return ESP_FAIL;
        }
        remaining -= (size_t)received;
    }
    free(buffer);
    result = ota_finish();
    if (result != ESP_OK) {
        ota_abort();
        return http_json(request, "400 Bad Request",
                         "{\"ok\":false,\"error\":\"invalid firmware image\"}");
    }
    esp_err_t response_result = http_json(request, NULL,
                                          "{\"ok\":true,\"message\":\"OTA verified; rebooting\"}");
    schedule_restart();
    return response_result;
}

static esp_err_t options_handler(httpd_req_t *request)
{
    http_common_headers(request);
    return httpd_resp_send(request, NULL, 0);
}

static esp_err_t http_server_start(void)
{
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.uri_match_fn = httpd_uri_match_wildcard;
    config.stack_size = 8192;
    config.max_uri_handlers = 12;
    httpd_handle_t server = NULL;
    ESP_RETURN_ON_ERROR(httpd_start(&server, &config), TAG, "HTTP server start failed");

    const httpd_uri_t status_uri = {
        .uri = "/api/status", .method = HTTP_GET, .handler = status_handler,
    };
    const httpd_uri_t control_uri = {
        .uri = "/api/control", .method = HTTP_POST, .handler = control_handler,
    };
    const httpd_uri_t wallpaper_uri = {
        .uri = "/api/wallpaper", .method = HTTP_POST, .handler = wallpaper_handler,
    };
    const httpd_uri_t ota_uri = {
        .uri = "/api/ota", .method = HTTP_POST, .handler = ota_handler,
    };
    const httpd_uri_t network_get_uri = {
        .uri = "/api/network", .method = HTTP_GET, .handler = network_handler,
    };
    const httpd_uri_t network_post_uri = {
        .uri = "/api/network", .method = HTTP_POST, .handler = network_handler,
    };
    const httpd_uri_t sensors_uri = {
        .uri = "/api/sensors", .method = HTTP_GET, .handler = sensors_handler,
    };
    const httpd_uri_t media_uri = {
        .uri = "/api/media/frame", .method = HTTP_POST, .handler = media_frame_handler,
    };
    const httpd_uri_t experiment_uri = {
        .uri = "/api/experiment", .method = HTTP_POST, .handler = experiment_handler,
    };
    const httpd_uri_t options_uri = {
        .uri = "/*", .method = HTTP_OPTIONS, .handler = options_handler,
    };
    ESP_ERROR_CHECK(httpd_register_uri_handler(server, &status_uri));
    ESP_ERROR_CHECK(httpd_register_uri_handler(server, &control_uri));
    ESP_ERROR_CHECK(httpd_register_uri_handler(server, &wallpaper_uri));
    ESP_ERROR_CHECK(httpd_register_uri_handler(server, &ota_uri));
    ESP_ERROR_CHECK(httpd_register_uri_handler(server, &network_get_uri));
    ESP_ERROR_CHECK(httpd_register_uri_handler(server, &network_post_uri));
    ESP_ERROR_CHECK(httpd_register_uri_handler(server, &sensors_uri));
    ESP_ERROR_CHECK(httpd_register_uri_handler(server, &media_uri));
    ESP_ERROR_CHECK(httpd_register_uri_handler(server, &experiment_uri));
    ESP_ERROR_CHECK(httpd_register_uri_handler(server, &options_uri));
    return ESP_OK;
}

static void mqtt_event_handler(void *argument, esp_event_base_t base, int32_t event_id,
                               void *event_data)
{
    (void)argument;
    (void)base;
    esp_mqtt_event_handle_t event = event_data;
    if (event_id == MQTT_EVENT_CONNECTED) {
        s_remote_connected = true;
        esp_mqtt_client_subscribe(event->client, s_mqtt_command_topic, 1);
        char status[384];
        labcapsule_build_status_json(status, sizeof(status));
        esp_mqtt_client_publish(event->client, s_mqtt_status_topic, status, 0, 1, 1);
        ESP_LOGI(TAG, "Remote MQTT connected");
    } else if (event_id == MQTT_EVENT_DISCONNECTED) {
        s_remote_connected = false;
    } else if (event_id == MQTT_EVENT_DATA && event->current_data_offset == 0 &&
               event->total_data_len == event->data_len && event->data_len > 0 &&
               event->data_len < 64) {
        char command[64] = {0};
        memcpy(command, event->data, event->data_len);
        char response[96];
        esp_err_t result = labcapsule_remote_action(command, response, sizeof(response));
        char payload[180];
        snprintf(payload, sizeof(payload),
                 "{\"ok\":%s,\"command\":\"%s\",\"message\":\"%s\"}",
                 result == ESP_OK ? "true" : "false", command, response);
        esp_mqtt_client_publish(event->client, s_mqtt_status_topic, payload, 0, 1, 0);
    }
}

static void mqtt_stop(void)
{
    s_remote_connected = false;
    if (s_mqtt_client) {
        esp_mqtt_client_stop(s_mqtt_client);
        esp_mqtt_client_destroy(s_mqtt_client);
        s_mqtt_client = NULL;
    }
}

static void mqtt_restart(void)
{
    mqtt_stop();
    const labcapsule_config_t *config = device_config_get();
    if (!s_sta_connected || !config->remote_enabled || !config->mqtt_uri[0]) return;
    snprintf(s_mqtt_command_topic, sizeof(s_mqtt_command_topic), "%s/%s/command",
             config->mqtt_topic[0] ? config->mqtt_topic : "labcapsule", s_device_name);
    snprintf(s_mqtt_status_topic, sizeof(s_mqtt_status_topic), "%s/%s/status",
             config->mqtt_topic[0] ? config->mqtt_topic : "labcapsule", s_device_name);
    esp_mqtt_client_config_t mqtt_config = {
        .broker.address.uri = config->mqtt_uri,
        .broker.verification.crt_bundle_attach = esp_crt_bundle_attach,
        .credentials.username = config->mqtt_username[0] ? config->mqtt_username : NULL,
        .credentials.authentication.password = config->mqtt_password[0]
            ? config->mqtt_password : NULL,
        .session.keepalive = 30,
        .network.reconnect_timeout_ms = 5000,
    };
    s_mqtt_client = esp_mqtt_client_init(&mqtt_config);
    if (!s_mqtt_client) return;
    esp_mqtt_client_register_event(s_mqtt_client, ESP_EVENT_ANY_ID,
                                   mqtt_event_handler, NULL);
    esp_mqtt_client_start(s_mqtt_client);
}

static void wifi_event_handler(void *argument, esp_event_base_t base, int32_t event_id,
                               void *event_data)
{
    (void)argument;
    if (base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        if (device_config_get()->wifi_ssid[0]) esp_wifi_connect();
    } else if (base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        s_sta_connected = false;
        strlcpy(s_sta_ip, "0.0.0.0", sizeof(s_sta_ip));
        mqtt_stop();
        if (device_config_get()->wifi_ssid[0]) {
            if (!device_config_get()->keep_recovery_ap) esp_wifi_set_mode(WIFI_MODE_APSTA);
            esp_wifi_connect();
        }
    } else if (base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event = event_data;
        snprintf(s_sta_ip, sizeof(s_sta_ip), IPSTR, IP2STR(&event->ip_info.ip));
        s_sta_connected = true;
        ESP_LOGI(TAG, "Wi-Fi station connected: %s", s_sta_ip);
        mqtt_restart();
        if (!device_config_get()->keep_recovery_ap) esp_wifi_set_mode(WIFI_MODE_STA);
    }
}

static esp_err_t wifi_start(void)
{
    ESP_RETURN_ON_ERROR(esp_netif_init(), TAG, "esp-netif init failed");
    esp_err_t loop_result = esp_event_loop_create_default();
    if (loop_result != ESP_OK && loop_result != ESP_ERR_INVALID_STATE) {
        return loop_result;
    }
    esp_netif_create_default_wifi_ap();
    esp_netif_t *station_netif = esp_netif_create_default_wifi_sta();
    if (station_netif) esp_netif_set_hostname(station_netif, s_device_name);
    wifi_init_config_t init_config = WIFI_INIT_CONFIG_DEFAULT();
    ESP_RETURN_ON_ERROR(esp_wifi_init(&init_config), TAG, "Wi-Fi init failed");

    wifi_config_t config = {0};
    strlcpy((char *)config.ap.ssid, s_ap_ssid, sizeof(config.ap.ssid));
    strlcpy((char *)config.ap.password, WIFI_AP_PASSWORD, sizeof(config.ap.password));
    config.ap.ssid_len = strlen(s_ap_ssid);
    config.ap.channel = 6;
    config.ap.max_connection = 4;
    config.ap.authmode = WIFI_AUTH_WPA2_PSK;
    config.ap.pmf_cfg.capable = true;
    config.ap.pmf_cfg.required = false;

    ESP_RETURN_ON_ERROR(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID,
                                                   wifi_event_handler, NULL), TAG,
                        "Wi-Fi event handler failed");
    ESP_RETURN_ON_ERROR(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP,
                                                   wifi_event_handler, NULL), TAG,
                        "IP event handler failed");
    ESP_RETURN_ON_ERROR(esp_wifi_set_mode(WIFI_MODE_APSTA), TAG, "Wi-Fi AP+STA mode failed");
    ESP_RETURN_ON_ERROR(esp_wifi_set_config(WIFI_IF_AP, &config), TAG,
                        "Wi-Fi AP config failed");
    wifi_config_t station = {0};
    const labcapsule_config_t *saved = device_config_get();
    strlcpy((char *)station.sta.ssid, saved->wifi_ssid, sizeof(station.sta.ssid));
    strlcpy((char *)station.sta.password, saved->wifi_password, sizeof(station.sta.password));
    station.sta.threshold.authmode = saved->wifi_password[0]
            ? WIFI_AUTH_WPA2_PSK : WIFI_AUTH_OPEN;
    station.sta.pmf_cfg.capable = true;
    ESP_RETURN_ON_ERROR(esp_wifi_set_config(WIFI_IF_STA, &station), TAG,
                        "Wi-Fi station config failed");
    ESP_RETURN_ON_ERROR(esp_wifi_start(), TAG, "Wi-Fi start failed");
    ESP_LOGI(TAG, "Wi-Fi AP %s started; password=%s; http://192.168.4.1",
             s_ap_ssid, WIFI_AP_PASSWORD);
    return http_server_start();
}

static int ble_access(uint16_t connection_handle, uint16_t attribute_handle,
                      struct ble_gatt_access_ctxt *context, void *argument)
{
    (void)connection_handle;
    (void)attribute_handle;
    (void)argument;
    const ble_uuid_t *uuid = context->chr->uuid;

    if (context->op == BLE_GATT_ACCESS_OP_READ_CHR &&
        ble_uuid_cmp(uuid, &s_status_uuid.u) == 0) {
        char status[384];
        labcapsule_build_status_json(status, sizeof(status));
        return os_mbuf_append(context->om, status, strlen(status)) == 0
                   ? 0 : BLE_ATT_ERR_INSUFFICIENT_RES;
    }

    if (context->op != BLE_GATT_ACCESS_OP_WRITE_CHR) {
        return BLE_ATT_ERR_READ_NOT_PERMITTED;
    }

    uint16_t length = OS_MBUF_PKTLEN(context->om);
    if (ble_uuid_cmp(uuid, &s_command_uuid.u) == 0) {
        if (length == 0 || length >= 64) {
            return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
        }
        char command[64] = {0};
        uint16_t copied = 0;
        if (ble_hs_mbuf_to_flat(context->om, command, sizeof(command) - 1, &copied) != 0) {
            return BLE_ATT_ERR_UNLIKELY;
        }
        char response[96];
        if (labcapsule_remote_action(command, response, sizeof(response)) != ESP_OK) {
            return BLE_ATT_ERR_UNLIKELY;
        }
        ble_gatts_chr_updated(s_ble_status_handle);
        return 0;
    }

    if (ble_uuid_cmp(uuid, &s_ota_control_uuid.u) == 0) {
        if (length == 0 || length >= 48) {
            return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
        }
        char command[48] = {0};
        uint16_t copied = 0;
        if (ble_hs_mbuf_to_flat(context->om, command, sizeof(command) - 1, &copied) != 0) {
            return BLE_ATT_ERR_UNLIKELY;
        }
        esp_err_t result;
        if (strncmp(command, "BEGIN:", 6) == 0) {
            result = ota_begin((size_t)strtoul(command + 6, NULL, 10));
        } else if (strcmp(command, "END") == 0) {
            result = ota_finish();
            if (result == ESP_OK) {
                ble_gatts_chr_updated(s_ble_status_handle);
                schedule_restart();
            }
        } else if (strcmp(command, "ABORT") == 0) {
            ota_abort();
            result = ESP_OK;
        } else {
            return BLE_ATT_ERR_UNLIKELY;
        }
        return result == ESP_OK ? 0 : BLE_ATT_ERR_UNLIKELY;
    }

    if (ble_uuid_cmp(uuid, &s_ota_data_uuid.u) == 0) {
        if (length == 0 || length > BLE_VALUE_MAX) {
            return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
        }
        uint8_t data[BLE_VALUE_MAX];
        uint16_t copied = 0;
        if (ble_hs_mbuf_to_flat(context->om, data, sizeof(data), &copied) != 0 ||
            ota_write(data, copied) != ESP_OK) {
            return BLE_ATT_ERR_UNLIKELY;
        }
        return 0;
    }

    if (ble_uuid_cmp(uuid, &s_file_control_uuid.u) == 0) {
        if (length == 0 || length >= MEDIA_CONTROL_MAX) {
            return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
        }
        char command[MEDIA_CONTROL_MAX] = {0};
        uint16_t copied = 0;
        if (ble_hs_mbuf_to_flat(context->om, command, sizeof(command) - 1, &copied) != 0) {
            return BLE_ATT_ERR_UNLIKELY;
        }
        esp_err_t result = ESP_ERR_NOT_SUPPORTED;
        if (strncmp(command, "BEGIN:", 6) == 0) {
            char kind[16] = {0};
            char encoding_name[16] = "raw565";
            unsigned size = 0;
            unsigned duration = 100;
            unsigned crc = 0;
            unsigned x = 0, y = 0, width = 240, height = 320;
            int fields = sscanf(command + 6,
                                "%15[^:]:%u:%u:%x:%15[^:]:%u:%u:%u:%u",
                                kind, &size, &duration, &crc, encoding_name,
                                &x, &y, &width, &height);
            labcapsule_media_encoding_t encoding = LABCAPSULE_MEDIA_RAW565;
            if (strcmp(encoding_name, "rle565") == 0) encoding = LABCAPSULE_MEDIA_RLE565;
            else if (strcmp(encoding_name, "rgb332") == 0) encoding = LABCAPSULE_MEDIA_RGB332;
            else if (strcmp(encoding_name, "rle332") == 0) encoding = LABCAPSULE_MEDIA_RLE332;
            if (fields >= 2 && x <= UINT16_MAX && y <= UINT16_MAX &&
                width <= UINT16_MAX && height <= UINT16_MAX) {
                if (strcmp(kind, "FRAME") == 0) {
                    result = file_transfer_begin(FILE_TRANSFER_FRAME, size, duration, crc,
                                                 encoding, x, y, width, height);
                } else if (strcmp(kind, "WALLPAPER") == 0) {
                    result = file_transfer_begin(FILE_TRANSFER_WALLPAPER, size, 0, crc,
                                                 LABCAPSULE_MEDIA_RAW565,
                                                 0, 0, 240, 320);
                }
            }
        } else if (strcmp(command, "END") == 0) {
            result = file_transfer_finish();
        } else if (strcmp(command, "ABORT") == 0) {
            file_transfer_abort();
            result = ESP_OK;
        }
        if (result == ESP_OK) ble_gatts_chr_updated(s_ble_status_handle);
        return result == ESP_OK ? 0 : BLE_ATT_ERR_UNLIKELY;
    }

    if (ble_uuid_cmp(uuid, &s_file_data_uuid.u) == 0) {
        if (length == 0 || length > BLE_VALUE_MAX) return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
        uint8_t data[BLE_VALUE_MAX];
        uint16_t copied = 0;
        if (ble_hs_mbuf_to_flat(context->om, data, sizeof(data), &copied) != 0 ||
            file_transfer_write(data, copied) != ESP_OK) return BLE_ATT_ERR_UNLIKELY;
        return 0;
    }
    return BLE_ATT_ERR_UNLIKELY;
}

static const struct ble_gatt_chr_def s_ble_characteristics[] = {
    {
        .uuid = &s_command_uuid.u,
        .access_cb = ble_access,
        .flags = BLE_GATT_CHR_F_WRITE,
    },
    {
        .uuid = &s_status_uuid.u,
        .access_cb = ble_access,
        .flags = BLE_GATT_CHR_F_READ | BLE_GATT_CHR_F_NOTIFY,
        .val_handle = &s_ble_status_handle,
    },
    {
        .uuid = &s_ota_control_uuid.u,
        .access_cb = ble_access,
        .flags = BLE_GATT_CHR_F_WRITE,
    },
    {
        .uuid = &s_ota_data_uuid.u,
        .access_cb = ble_access,
        .flags = BLE_GATT_CHR_F_WRITE,
    },
    {
        .uuid = &s_file_control_uuid.u,
        .access_cb = ble_access,
        .flags = BLE_GATT_CHR_F_WRITE,
    },
    {
        .uuid = &s_file_data_uuid.u,
        .access_cb = ble_access,
        .flags = BLE_GATT_CHR_F_WRITE,
    },
    {0},
};

static const struct ble_gatt_svc_def s_ble_services[] = {
    {
        .type = BLE_GATT_SVC_TYPE_PRIMARY,
        .uuid = &s_service_uuid.u,
        .characteristics = s_ble_characteristics,
    },
    {0},
};

static void ble_advertise(void);

static int ble_gap_event(struct ble_gap_event *event, void *argument)
{
    (void)argument;
    switch (event->type) {
        case BLE_GAP_EVENT_CONNECT:
            if (event->connect.status != 0) {
                ble_advertise();
            }
            return 0;
        case BLE_GAP_EVENT_DISCONNECT:
        case BLE_GAP_EVENT_ADV_COMPLETE:
            ble_advertise();
            return 0;
        default:
            return 0;
    }
}

static void ble_advertise(void)
{
    struct ble_hs_adv_fields fields = {0};
    fields.flags = BLE_HS_ADV_F_DISC_GEN | BLE_HS_ADV_F_BREDR_UNSUP;
    fields.name = (uint8_t *)s_device_name;
    fields.name_len = strlen(s_device_name);
    fields.name_is_complete = 1;
    int result = ble_gap_adv_set_fields(&fields);
    if (result != 0) {
        ESP_LOGE(TAG, "BLE advertisement fields failed: %d", result);
        return;
    }

    struct ble_hs_adv_fields response = {0};
    response.uuids128 = (ble_uuid128_t *)&s_service_uuid;
    response.num_uuids128 = 1;
    response.uuids128_is_complete = 1;
    ble_gap_adv_rsp_set_fields(&response);

    struct ble_gap_adv_params parameters = {0};
    parameters.conn_mode = BLE_GAP_CONN_MODE_UND;
    parameters.disc_mode = BLE_GAP_DISC_MODE_GEN;
    result = ble_gap_adv_start(s_ble_own_addr_type, NULL, BLE_HS_FOREVER,
                               &parameters, ble_gap_event, NULL);
    if (result != 0 && result != BLE_HS_EALREADY) {
        ESP_LOGE(TAG, "BLE advertising failed: %d", result);
    }
}

static void ble_on_reset(int reason)
{
    ESP_LOGW(TAG, "NimBLE reset: %d", reason);
}

static void ble_on_sync(void)
{
    if (ble_hs_util_ensure_addr(0) != 0 ||
        ble_hs_id_infer_auto(0, &s_ble_own_addr_type) != 0) {
        ESP_LOGE(TAG, "No BLE identity address");
        return;
    }
    ble_advertise();
}

static void ble_host_task(void *argument)
{
    (void)argument;
    nimble_port_run();
    nimble_port_freertos_deinit();
}

static esp_err_t ble_start(void)
{
    ESP_RETURN_ON_ERROR(nimble_port_init(), TAG, "NimBLE init failed");
    ble_hs_cfg.reset_cb = ble_on_reset;
    ble_hs_cfg.sync_cb = ble_on_sync;
    ble_svc_gap_init();
    ble_svc_gatt_init();
    int result = ble_gatts_count_cfg(s_ble_services);
    if (result == 0) {
        result = ble_gatts_add_svcs(s_ble_services);
    }
    if (result != 0) {
        return ESP_FAIL;
    }
    ble_svc_gap_device_name_set(s_device_name);
    ble_att_set_preferred_mtu(517);
    nimble_port_freertos_init(ble_host_task);
    ESP_LOGI(TAG, "BLE service %s started", s_device_name);
    return ESP_OK;
}

esp_err_t connectivity_start(void)
{
    esp_err_t nvs_result = nvs_flash_init();
    if (nvs_result == ESP_ERR_NVS_NO_FREE_PAGES ||
        nvs_result == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_RETURN_ON_ERROR(nvs_flash_erase(), TAG, "NVS erase failed");
        nvs_result = nvs_flash_init();
    }
    ESP_RETURN_ON_ERROR(nvs_result, TAG, "NVS init failed");
    ESP_RETURN_ON_ERROR(device_config_init(), TAG, "Device configuration failed");

    uint8_t mac[6];
    ESP_RETURN_ON_ERROR(esp_read_mac(mac, ESP_MAC_WIFI_SOFTAP), TAG,
                        "MAC read failed");
    snprintf(s_device_name, sizeof(s_device_name), "LabCapsule-%02X%02X",
             mac[4], mac[5]);
    strlcpy(s_ap_ssid, s_device_name, sizeof(s_ap_ssid));

    ESP_RETURN_ON_ERROR(wifi_start(), TAG, "Wi-Fi services failed");
    ESP_RETURN_ON_ERROR(ble_start(), TAG, "BLE services failed");
    return ESP_OK;
}
