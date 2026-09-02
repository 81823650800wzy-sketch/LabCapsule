#include "sensor_hub.h"

#include <stdio.h>
#include <string.h>

#include "esp_log.h"

#define MAX_SENSOR_DRIVERS 16

typedef struct {
    sensor_driver_t driver;
    bool detected;
} sensor_slot_t;

static const char *TAG = "SensorHub";
static sensor_slot_t s_slots[MAX_SENSOR_DRIVERS];
static size_t s_slot_count;
static i2c_master_bus_handle_t s_i2c_bus;
static SemaphoreHandle_t s_bus_mutex;
static volatile bool s_scan_enabled = true;

static const sensor_driver_t s_known_sensors[] = {
    {.id="mpu6050", .display_name="MPU6050", .bus=SENSOR_BUS_I2C, .address=0x68,
     .capabilities="acceleration,gyroscope,temperature"},
    {.id="bme280", .display_name="BME280/BMP280", .bus=SENSOR_BUS_I2C, .address=0x76,
     .capabilities="temperature,humidity,pressure"},
    {.id="sht3x", .display_name="SHT30/SHT31", .bus=SENSOR_BUS_I2C, .address=0x44,
     .capabilities="temperature,humidity"},
    {.id="ina219", .display_name="INA219", .bus=SENSOR_BUS_I2C, .address=0x40,
     .capabilities="voltage,current,power"},
    {.id="ads1115", .display_name="ADS1115", .bus=SENSOR_BUS_I2C, .address=0x48,
     .capabilities="analog"},
    {.id="vl53l0x", .display_name="VL53L0X", .bus=SENSOR_BUS_I2C, .address=0x29,
     .capabilities="distance"},
};

esp_err_t sensor_hub_register(const sensor_driver_t *driver)
{
    if (!driver || !driver->id || !driver->display_name || s_slot_count >= MAX_SENSOR_DRIVERS) {
        return ESP_ERR_INVALID_ARG;
    }
    s_slots[s_slot_count++].driver = *driver;
    return ESP_OK;
}

esp_err_t sensor_hub_init(i2c_master_bus_handle_t i2c_bus, SemaphoreHandle_t bus_mutex)
{
    s_i2c_bus = i2c_bus;
    s_bus_mutex = bus_mutex;
    s_slot_count = 0;
    for (size_t i = 0; i < sizeof(s_known_sensors) / sizeof(s_known_sensors[0]); ++i) {
        sensor_hub_register(&s_known_sensors[i]);
    }
    sensor_hub_discover();
    return ESP_OK;
}

void sensor_hub_set_scan_enabled(bool enabled)
{
    s_scan_enabled = enabled;
}

void sensor_hub_set_primary_ready(const char *id, bool ready)
{
    for (size_t i = 0; id && i < s_slot_count; ++i) {
        if (strcmp(s_slots[i].driver.id, id) == 0) s_slots[i].detected = ready;
    }
}

size_t sensor_hub_discover(void)
{
    size_t found = 0;
    if (!s_scan_enabled) {
        for (size_t i = 0; i < s_slot_count; ++i)
            if (s_slots[i].detected) ++found;
        return found;
    }
    if (s_bus_mutex) xSemaphoreTake(s_bus_mutex, portMAX_DELAY);
    for (size_t i = 0; i < s_slot_count; ++i) {
        sensor_slot_t *slot = &s_slots[i];
        if (slot->driver.bus != SENSOR_BUS_I2C || !s_i2c_bus) continue;
        /* The primary MPU is already registered with the IDF I2C driver.  On
         * ESP32-S3, probing that address again while its device handle is
         * active may report busy/not-found even though live sampling works.
         * Its owning driver explicitly maintains this readiness bit. */
        if (strcmp(slot->driver.id, "mpu6050") == 0 && slot->detected) {
            ++found;
            continue;
        }
        esp_err_t result = slot->driver.probe
            ? slot->driver.probe(s_i2c_bus, slot->driver.address)
            : i2c_master_probe(s_i2c_bus, slot->driver.address, 60);
        slot->detected = result == ESP_OK;
        if (slot->detected) {
            ++found;
            ESP_LOGI(TAG, "Detected %s at I2C 0x%02x", slot->driver.display_name,
                     slot->driver.address);
        }
    }
    if (s_bus_mutex) xSemaphoreGive(s_bus_mutex);
    return found;
}

void sensor_hub_build_json(char *buffer, size_t buffer_size)
{
    if (!buffer || buffer_size == 0) return;
    size_t used = snprintf(buffer, buffer_size, "{\"connector\":{\"i2c\":\"GPIO8/9\","
                           "\"spi\":\"extensible\",\"uart\":\"extensible\"},\"sensors\":[");
    for (size_t i = 0; i < s_slot_count && used < buffer_size; ++i) {
        sensor_slot_t *slot = &s_slots[i];
        int written = snprintf(buffer + used, buffer_size - used,
            "%s{\"id\":\"%s\",\"name\":\"%s\",\"bus\":\"%s\",\"address\":%u,"
            "\"detected\":%s,\"capabilities\":\"%s\"}",
            i ? "," : "", slot->driver.id, slot->driver.display_name,
            slot->driver.bus == SENSOR_BUS_I2C ? "i2c" : "extension",
            slot->driver.address, slot->detected ? "true" : "false",
            slot->driver.capabilities ? slot->driver.capabilities : "");
        if (written < 0 || (size_t)written >= buffer_size - used) break;
        used += (size_t)written;
    }
    if (used + 3 < buffer_size) snprintf(buffer + used, buffer_size - used, "]}");
}

void sensor_hub_build_ble_json(char *buffer, size_t buffer_size)
{
    if (!buffer || buffer_size == 0) return;
    size_t found = 0;
    for (size_t i = 0; i < s_slot_count; ++i) {
        if (s_slots[i].detected) ++found;
    }
    size_t used = snprintf(buffer, buffer_size,
                           "{\"ok\":true,\"type\":\"sensors\",\"count\":%u,"
                           "\"i2c\":\"SDA GPIO8 / SCL GPIO9\",\"sensors\":[",
                           (unsigned)found);
    bool first = true;
    for (size_t i = 0; i < s_slot_count && used < buffer_size; ++i) {
        const sensor_slot_t *slot = &s_slots[i];
        if (!slot->detected) continue;
        int written = snprintf(buffer + used, buffer_size - used,
                               "%s{\"id\":\"%s\",\"name\":\"%s\","
                               "\"bus\":\"i2c\",\"address\":\"0x%02X\"}",
                               first ? "" : ",", slot->driver.id,
                               slot->driver.display_name, slot->driver.address);
        if (written < 0 || (size_t)written >= buffer_size - used) break;
        used += (size_t)written;
        first = false;
    }
    if (used + 3 < buffer_size) snprintf(buffer + used, buffer_size - used, "]}");
}
