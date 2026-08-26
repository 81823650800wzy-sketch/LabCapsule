#pragma once

#include "esp_err.h"

/** Start AP+STA Wi-Fi, HTTP/MQTT remote services and the BLE GATT service. */
esp_err_t connectivity_start(void);

/** Redacted runtime network state for diagnostics. */
void connectivity_build_status_json(char *buffer, size_t buffer_size);
