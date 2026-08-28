#include "input_hub.h"

#include <stdbool.h>
#include <string.h>

#include "esp_timer.h"

#define INPUT_DRIVER_CAPACITY 8

typedef struct {
    input_driver_t descriptor;
    input_action_mask_t sampled;
    input_action_mask_t stable;
    int64_t changed_us[INPUT_ACTION_COUNT];
} registered_driver_t;

static registered_driver_t s_drivers[INPUT_DRIVER_CAPACITY];
static size_t s_driver_count;
static input_event_fn s_callback;
static void *s_callback_context;

esp_err_t input_hub_init(input_event_fn callback, void *context)
{
    if (!callback) return ESP_ERR_INVALID_ARG;
    memset(s_drivers, 0, sizeof(s_drivers));
    s_driver_count = 0;
    s_callback = callback;
    s_callback_context = context;
    return ESP_OK;
}

esp_err_t input_hub_register(const input_driver_t *driver)
{
    if (!driver || !driver->id || !driver->id[0] || !driver->poll ||
        s_driver_count >= INPUT_DRIVER_CAPACITY) return ESP_ERR_INVALID_ARG;
    for (size_t index = 0; index < s_driver_count; ++index) {
        if (strcmp(s_drivers[index].descriptor.id, driver->id) == 0)
            return ESP_ERR_INVALID_STATE;
    }
    registered_driver_t *slot = &s_drivers[s_driver_count++];
    slot->descriptor = *driver;
    if (slot->descriptor.debounce_ms == 0) slot->descriptor.debounce_ms = 30;
    int64_t now = esp_timer_get_time();
    for (size_t action = 0; action < INPUT_ACTION_COUNT; ++action)
        slot->changed_us[action] = now;
    return ESP_OK;
}

void input_hub_poll(void)
{
    const input_action_mask_t valid_mask = (1UL << INPUT_ACTION_COUNT) - 1UL;
    int64_t now = esp_timer_get_time();
    for (size_t driver_index = 0; driver_index < s_driver_count; ++driver_index) {
        registered_driver_t *driver = &s_drivers[driver_index];
        input_action_mask_t current = driver->descriptor.poll(driver->descriptor.context) &
                valid_mask;
        input_action_mask_t changed = current ^ driver->sampled;
        if (changed) {
            driver->sampled = current;
            for (size_t action = 0; action < INPUT_ACTION_COUNT; ++action) {
                if (changed & INPUT_ACTION_BIT(action)) driver->changed_us[action] = now;
            }
        }
        for (size_t action = 0; action < INPUT_ACTION_COUNT; ++action) {
            input_action_mask_t bit = INPUT_ACTION_BIT(action);
            bool sampled_pressed = (driver->sampled & bit) != 0;
            bool stable_pressed = (driver->stable & bit) != 0;
            if (sampled_pressed == stable_pressed ||
                now - driver->changed_us[action] <
                    (int64_t)driver->descriptor.debounce_ms * 1000LL) continue;
            if (sampled_pressed) driver->stable |= bit; else driver->stable &= ~bit;
            if (sampled_pressed && s_callback)
                s_callback((input_action_t)action, driver->descriptor.id,
                           s_callback_context);
        }
    }
}

void input_hub_emit(input_action_t action, const char *source)
{
    if ((unsigned)action >= INPUT_ACTION_COUNT || !s_callback) return;
    s_callback(action, source ? source : "software", s_callback_context);
}

size_t input_hub_driver_count(void)
{
    return s_driver_count;
}

