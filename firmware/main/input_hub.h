#pragma once

#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"

typedef enum {
    INPUT_ACTION_UP = 0,
    INPUT_ACTION_DOWN,
    INPUT_ACTION_LEFT,
    INPUT_ACTION_RIGHT,
    INPUT_ACTION_OK,
    INPUT_ACTION_BACK,
    INPUT_ACTION_COUNT,
} input_action_t;

typedef uint32_t input_action_mask_t;

#define INPUT_ACTION_BIT(action) (1UL << (unsigned)(action))

typedef input_action_mask_t (*input_driver_poll_fn)(void *context);
typedef void (*input_event_fn)(input_action_t action, const char *source, void *context);

typedef struct {
    const char *id;
    input_driver_poll_fn poll;
    void *context;
    uint16_t debounce_ms;
} input_driver_t;

/** Initialize the logical input dispatcher. */
esp_err_t input_hub_init(input_event_fn callback, void *context);

/** Register a GPIO, analog joystick, key matrix or external-bus input driver. */
esp_err_t input_hub_register(const input_driver_t *driver);

/** Poll every registered driver once. Call this from one periodic FreeRTOS task. */
void input_hub_poll(void);

/** Inject a logical event from BLE, HTTP or another software source. */
void input_hub_emit(input_action_t action, const char *source);

/** Number of currently registered physical/logical input drivers. */
size_t input_hub_driver_count(void);

