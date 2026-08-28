#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"

typedef struct {
    bool ready;
    bool recording;
    bool full;
    uint32_t sessions;
    uint32_t samples;
    uint32_t current_samples;
    uint32_t dropped_samples;
    uint64_t bytes_used;
    uint64_t bytes_capacity;
} offline_store_info_t;

/** Mount the wear-levelled FAT partition and recover interrupted temporary sessions. */
esp_err_t offline_store_init(void);

/** Create a session container. It is removed on finish when every sample was streamed live. */
esp_err_t offline_store_start(uint32_t rate_hz, uint32_t duration_seconds);

/** Queue one compact six-axis sample without blocking the high-priority sampler. */
bool offline_store_enqueue(uint32_t elapsed_us, float ax, float ay, float az,
                           float gx, float gy, float gz);

/** Drain queued records and atomically finalize or discard the current session. */
esp_err_t offline_store_finish(bool aborted);

void offline_store_get_info(offline_store_info_t *info);
void offline_store_build_json(char *buffer, size_t buffer_size);

/** Delete every completed offline session. Rejected while an experiment is recording. */
esp_err_t offline_store_clear(void);

/** Open a stable snapshot and read concatenated LCB1 session files. */
esp_err_t offline_store_export_open(void);
size_t offline_store_export_read(uint8_t *buffer, size_t capacity);
void offline_store_export_close(void);

