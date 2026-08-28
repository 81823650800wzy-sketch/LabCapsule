#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"

/** Start AP+STA Wi-Fi, HTTP/MQTT remote services and the BLE GATT service. */
esp_err_t connectivity_start(void);

/** Redacted runtime network state for diagnostics. */
void connectivity_build_status_json(char *buffer, size_t buffer_size);

/**
 * Send one live six-axis sample to subscribed BLE/MQTT clients.
 * Returns true only when at least one live transport accepted the sample.
 */
bool connectivity_stream_motion(uint32_t elapsed_us, float ax, float ay, float az,
                                float gx, float gy, float gz);
