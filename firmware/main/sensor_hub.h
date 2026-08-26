#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "driver/i2c_master.h"
#include "esp_err.h"

typedef enum {
    SENSOR_BUS_I2C,
    SENSOR_BUS_SPI,
    SENSOR_BUS_UART,
    SENSOR_BUS_ADC,
    SENSOR_BUS_ONEWIRE,
} sensor_bus_t;

typedef struct {
    const char *id;
    const char *display_name;
    sensor_bus_t bus;
    uint8_t address;
    const char *capabilities;
    esp_err_t (*probe)(void *bus_handle, uint8_t address);
    esp_err_t (*start)(void);
    esp_err_t (*sample_json)(char *buffer, size_t buffer_size);
} sensor_driver_t;

esp_err_t sensor_hub_init(i2c_master_bus_handle_t i2c_bus);
esp_err_t sensor_hub_register(const sensor_driver_t *driver);
void sensor_hub_set_primary_ready(const char *id, bool ready);
size_t sensor_hub_discover(void);
void sensor_hub_build_json(char *buffer, size_t buffer_size);
