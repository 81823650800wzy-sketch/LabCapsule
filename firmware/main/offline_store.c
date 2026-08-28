#include "offline_store.h"

#include <dirent.h>
#include <ctype.h>
#include <errno.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include "esp_check.h"
#include "esp_log.h"
#include "esp_random.h"
#include "esp_vfs_fat.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "wear_levelling.h"

#define OFFLINE_BASE_PATH "/offline"
#define OFFLINE_PARTITION_LABEL "offline"
#define OFFLINE_MAGIC 0x3142434CUL
#define OFFLINE_VERSION 1U
#define OFFLINE_FLAG_COMPLETE 0x01U
#define OFFLINE_FLAG_ABORTED 0x02U
#define OFFLINE_FLAG_RECOVERED 0x04U
#define OFFLINE_QUEUE_DEPTH 512U

typedef struct __attribute__((packed)) {
    uint32_t magic;
    uint16_t version;
    uint16_t header_size;
    uint32_t session_id;
    uint32_t sample_rate_hz;
    uint32_t duration_seconds;
    uint32_t sample_count;
    uint32_t dropped_count;
    uint32_t flags;
} offline_header_t;

typedef struct __attribute__((packed)) {
    uint32_t elapsed_us;
    int16_t axis[6];
} offline_sample_t;

typedef enum {
    STORE_MESSAGE_SAMPLE = 0,
    STORE_MESSAGE_FINISH,
} store_message_type_t;

typedef struct {
    store_message_type_t type;
    offline_sample_t sample;
    bool aborted;
} store_message_t;

_Static_assert(sizeof(offline_header_t) == 32, "offline header must stay stable");
_Static_assert(sizeof(offline_sample_t) == 16, "offline sample must stay stable");

static const char *TAG = "OfflineStore";
static wl_handle_t s_wl_handle = WL_INVALID_HANDLE;
static SemaphoreHandle_t s_lock;
static SemaphoreHandle_t s_finished;
static QueueHandle_t s_queue;
static FILE *s_active_file;
static char s_active_path[64];
static offline_header_t s_active_header;
static offline_store_info_t s_info;
static volatile uint32_t s_pending_dropped;
static DIR *s_export_directory;
static FILE *s_export_file;

static bool has_suffix(const char *name, const char *suffix)
{
    size_t name_length = name ? strlen(name) : 0;
    size_t suffix_length = suffix ? strlen(suffix) : 0;
    if (name_length < suffix_length) return false;
    const char *tail = name + name_length - suffix_length;
    for (size_t index = 0; index < suffix_length; ++index) {
        if (tolower((unsigned char)tail[index]) !=
            tolower((unsigned char)suffix[index])) return false;
    }
    return true;
}

static int16_t quantize(float value, float scale)
{
    long converted = lrintf(value * scale);
    if (converted > INT16_MAX) converted = INT16_MAX;
    if (converted < INT16_MIN) converted = INT16_MIN;
    return (int16_t)converted;
}

static void export_close_locked(void)
{
    if (s_export_file) fclose(s_export_file);
    if (s_export_directory) closedir(s_export_directory);
    s_export_file = NULL;
    s_export_directory = NULL;
}

static void scan_locked(void)
{
    uint32_t sessions = 0;
    uint64_t samples = 0;
    uint64_t bytes = 0;
    DIR *directory = opendir(OFFLINE_BASE_PATH);
    if (directory) {
        struct dirent *entry;
        while ((entry = readdir(directory)) != NULL) {
            if (!has_suffix(entry->d_name, ".lcb")) continue;
            char path[320];
            snprintf(path, sizeof(path), "%s/%s", OFFLINE_BASE_PATH, entry->d_name);
            FILE *file = fopen(path, "rb");
            if (!file) continue;
            offline_header_t header = {0};
            bool valid = fread(&header, 1, sizeof(header), file) == sizeof(header) &&
                    header.magic == OFFLINE_MAGIC && header.version == OFFLINE_VERSION &&
                    header.header_size == sizeof(header);
            if (fseek(file, 0, SEEK_END) == 0) {
                long length = ftell(file);
                if (length > 0) bytes += (uint64_t)length;
            }
            fclose(file);
            if (valid) {
                ++sessions;
                samples += header.sample_count;
            }
        }
        closedir(directory);
    }
    s_info.sessions = sessions;
    s_info.samples = samples > UINT32_MAX ? UINT32_MAX : (uint32_t)samples;
    s_info.bytes_used = bytes;
}

static void recover_temporary_files(void)
{
    DIR *directory = opendir(OFFLINE_BASE_PATH);
    if (!directory) return;
    struct dirent *entry;
    while ((entry = readdir(directory)) != NULL) {
        if (!has_suffix(entry->d_name, ".tmp")) continue;
        char source[320];
        snprintf(source, sizeof(source), "%s/%s", OFFLINE_BASE_PATH, entry->d_name);
        FILE *file = fopen(source, "r+b");
        if (!file) continue;
        offline_header_t header = {0};
        bool valid = fread(&header, 1, sizeof(header), file) == sizeof(header) &&
                header.magic == OFFLINE_MAGIC && header.version == OFFLINE_VERSION;
        long length = -1;
        if (valid && fseek(file, 0, SEEK_END) == 0) length = ftell(file);
        if (valid && length >= (long)sizeof(header)) {
            header.sample_count = (uint32_t)((length - sizeof(header)) /
                                             sizeof(offline_sample_t));
            header.flags = OFFLINE_FLAG_RECOVERED;
            fseek(file, 0, SEEK_SET);
            fwrite(&header, 1, sizeof(header), file);
            fflush(file);
        }
        fclose(file);
        if (!valid || header.sample_count == 0) {
            unlink(source);
            continue;
        }
        char destination[320];
        strlcpy(destination, source, sizeof(destination));
        char *extension = strrchr(destination, '.');
        if (extension) strlcpy(extension, ".lcb", 5);
        rename(source, destination);
    }
    closedir(directory);
}

static void finalize_locked(bool aborted)
{
    if (!s_active_file) return;
    s_active_header.dropped_count += s_pending_dropped;
    s_pending_dropped = 0;
    s_active_header.flags = aborted ? OFFLINE_FLAG_ABORTED : OFFLINE_FLAG_COMPLETE;
    fflush(s_active_file);
    fseek(s_active_file, 0, SEEK_SET);
    fwrite(&s_active_header, 1, sizeof(s_active_header), s_active_file);
    fflush(s_active_file);
    fclose(s_active_file);
    s_active_file = NULL;
    s_info.recording = false;
    if (s_active_header.sample_count == 0) {
        unlink(s_active_path);
    } else {
        char completed[64];
        strlcpy(completed, s_active_path, sizeof(completed));
        char *extension = strrchr(completed, '.');
        if (extension) strlcpy(extension, ".lcb", 5);
        if (rename(s_active_path, completed) != 0)
            ESP_LOGE(TAG, "Session rename failed: errno=%d", errno);
    }
    s_active_path[0] = '\0';
    s_info.current_samples = 0;
    scan_locked();
}

static void storage_task(void *argument)
{
    (void)argument;
    store_message_t message;
    while (true) {
        if (xQueueReceive(s_queue, &message, portMAX_DELAY) != pdTRUE) continue;
        xSemaphoreTake(s_lock, portMAX_DELAY);
        if (message.type == STORE_MESSAGE_SAMPLE && s_active_file) {
            if (fwrite(&message.sample, 1, sizeof(message.sample), s_active_file) ==
                    sizeof(message.sample)) {
                ++s_active_header.sample_count;
                s_info.current_samples = s_active_header.sample_count;
            } else {
                s_info.full = true;
                ++s_active_header.dropped_count;
            }
        } else if (message.type == STORE_MESSAGE_FINISH) {
            finalize_locked(message.aborted);
        }
        xSemaphoreGive(s_lock);
        if (message.type == STORE_MESSAGE_FINISH) xSemaphoreGive(s_finished);
    }
}

esp_err_t offline_store_init(void)
{
    s_lock = xSemaphoreCreateMutex();
    s_finished = xSemaphoreCreateBinary();
    s_queue = xQueueCreate(OFFLINE_QUEUE_DEPTH, sizeof(store_message_t));
    if (!s_lock || !s_finished || !s_queue) return ESP_ERR_NO_MEM;
    const esp_vfs_fat_mount_config_t config = {
        .format_if_mount_failed = true,
        .max_files = 5,
        .allocation_unit_size = 4096,
    };
    ESP_RETURN_ON_ERROR(esp_vfs_fat_spiflash_mount_rw_wl(OFFLINE_BASE_PATH,
                        OFFLINE_PARTITION_LABEL, &config, &s_wl_handle), TAG,
                        "Offline partition mount failed");
    uint64_t free_bytes = 0;
    uint64_t total_bytes = 0;
    if (esp_vfs_fat_info(OFFLINE_BASE_PATH, &total_bytes, &free_bytes) == ESP_OK)
        s_info.bytes_capacity = total_bytes;
    s_info.ready = true;
    recover_temporary_files();
    scan_locked();
    if (xTaskCreate(storage_task, "offline_storage", 4096, NULL, 6, NULL) != pdPASS)
        return ESP_ERR_NO_MEM;
    ESP_LOGI(TAG, "Offline storage ready: %llu bytes, %lu sessions",
             (unsigned long long)s_info.bytes_capacity, (unsigned long)s_info.sessions);
    return ESP_OK;
}

esp_err_t offline_store_start(uint32_t rate_hz, uint32_t duration_seconds)
{
    if (!s_info.ready || !s_lock || rate_hz == 0 || duration_seconds == 0)
        return ESP_ERR_INVALID_STATE;
    xSemaphoreTake(s_lock, portMAX_DELAY);
    if (s_active_file) {
        xSemaphoreGive(s_lock);
        return ESP_ERR_INVALID_STATE;
    }
    export_close_locked();
    uint32_t session_id = esp_random();
    for (unsigned attempt = 0; attempt < 8; ++attempt) {
        snprintf(s_active_path, sizeof(s_active_path), "%s/%08lx.tmp",
                 OFFLINE_BASE_PATH, (unsigned long)session_id);
        if (access(s_active_path, F_OK) != 0) break;
        session_id = esp_random();
    }
    s_active_file = fopen(s_active_path, "w+b");
    if (!s_active_file) {
        s_info.full = true;
        xSemaphoreGive(s_lock);
        return ESP_FAIL;
    }
    setvbuf(s_active_file, NULL, _IOFBF, 16384);
    s_active_header = (offline_header_t){
        .magic = OFFLINE_MAGIC,
        .version = OFFLINE_VERSION,
        .header_size = sizeof(offline_header_t),
        .session_id = session_id,
        .sample_rate_hz = rate_hz,
        .duration_seconds = duration_seconds,
    };
    if (fwrite(&s_active_header, 1, sizeof(s_active_header), s_active_file) !=
            sizeof(s_active_header) || fflush(s_active_file) != 0) {
        fclose(s_active_file);
        s_active_file = NULL;
        unlink(s_active_path);
        s_info.full = true;
        xSemaphoreGive(s_lock);
        return ESP_FAIL;
    }
    s_pending_dropped = 0;
    s_info.current_samples = 0;
    s_info.dropped_samples = 0;
    s_info.recording = true;
    s_info.full = false;
    xSemaphoreGive(s_lock);
    return ESP_OK;
}

bool offline_store_enqueue(uint32_t elapsed_us, float ax, float ay, float az,
                           float gx, float gy, float gz)
{
    if (!s_info.recording || !s_queue) return false;
    store_message_t message = {
        .type = STORE_MESSAGE_SAMPLE,
        .sample = {
            .elapsed_us = elapsed_us,
            .axis = {
                quantize(ax, 4096.0f), quantize(ay, 4096.0f),
                quantize(az, 4096.0f), quantize(gx, 16.0f),
                quantize(gy, 16.0f), quantize(gz, 16.0f),
            },
        },
    };
    if (xQueueSend(s_queue, &message, 0) == pdTRUE) return true;
    ++s_pending_dropped;
    s_info.dropped_samples = s_pending_dropped;
    return false;
}

esp_err_t offline_store_finish(bool aborted)
{
    if (!s_info.recording || !s_queue) return ESP_ERR_INVALID_STATE;
    store_message_t message = {.type = STORE_MESSAGE_FINISH, .aborted = aborted};
    if (xQueueSend(s_queue, &message, pdMS_TO_TICKS(1000)) != pdTRUE)
        return ESP_ERR_TIMEOUT;
    return xSemaphoreTake(s_finished, pdMS_TO_TICKS(10000)) == pdTRUE
            ? ESP_OK : ESP_ERR_TIMEOUT;
}

void offline_store_get_info(offline_store_info_t *info)
{
    if (!info) return;
    if (s_lock) xSemaphoreTake(s_lock, portMAX_DELAY);
    *info = s_info;
    info->dropped_samples += s_pending_dropped;
    if (s_lock) xSemaphoreGive(s_lock);
}

void offline_store_build_json(char *buffer, size_t buffer_size)
{
    if (!buffer || buffer_size == 0) return;
    offline_store_info_t info;
    offline_store_get_info(&info);
    snprintf(buffer, buffer_size,
             "{\"ready\":%s,\"recording\":%s,\"full\":%s,"
             "\"sessions\":%lu,\"samples\":%lu,\"currentSamples\":%lu,"
             "\"droppedSamples\":%lu,\"bytesUsed\":%llu,\"bytesCapacity\":%llu}",
             info.ready ? "true" : "false", info.recording ? "true" : "false",
             info.full ? "true" : "false", (unsigned long)info.sessions,
             (unsigned long)info.samples, (unsigned long)info.current_samples,
             (unsigned long)info.dropped_samples, (unsigned long long)info.bytes_used,
             (unsigned long long)info.bytes_capacity);
}

esp_err_t offline_store_clear(void)
{
    if (!s_info.ready || !s_lock) return ESP_ERR_INVALID_STATE;
    xSemaphoreTake(s_lock, portMAX_DELAY);
    if (s_active_file) {
        xSemaphoreGive(s_lock);
        return ESP_ERR_INVALID_STATE;
    }
    export_close_locked();
    DIR *directory = opendir(OFFLINE_BASE_PATH);
    if (directory) {
        struct dirent *entry;
        while ((entry = readdir(directory)) != NULL) {
            if (!has_suffix(entry->d_name, ".lcb") &&
                !has_suffix(entry->d_name, ".tmp")) continue;
            char path[320];
            snprintf(path, sizeof(path), "%s/%s", OFFLINE_BASE_PATH, entry->d_name);
            unlink(path);
        }
        closedir(directory);
    }
    s_info.full = false;
    scan_locked();
    xSemaphoreGive(s_lock);
    return ESP_OK;
}

esp_err_t offline_store_export_open(void)
{
    if (!s_info.ready || !s_lock) return ESP_ERR_INVALID_STATE;
    xSemaphoreTake(s_lock, portMAX_DELAY);
    if (s_active_file) {
        xSemaphoreGive(s_lock);
        return ESP_ERR_INVALID_STATE;
    }
    export_close_locked();
    s_export_directory = opendir(OFFLINE_BASE_PATH);
    xSemaphoreGive(s_lock);
    return s_export_directory ? ESP_OK : ESP_FAIL;
}

static bool export_open_next_locked(void)
{
    if (!s_export_directory) return false;
    struct dirent *entry;
    while ((entry = readdir(s_export_directory)) != NULL) {
        if (!has_suffix(entry->d_name, ".lcb")) continue;
        char path[320];
        snprintf(path, sizeof(path), "%s/%s", OFFLINE_BASE_PATH, entry->d_name);
        s_export_file = fopen(path, "rb");
        if (s_export_file) return true;
    }
    return false;
}

size_t offline_store_export_read(uint8_t *buffer, size_t capacity)
{
    if (!buffer || capacity == 0 || !s_lock) return 0;
    xSemaphoreTake(s_lock, portMAX_DELAY);
    size_t total = 0;
    while (total < capacity) {
        if (!s_export_file && !export_open_next_locked()) break;
        size_t count = fread(buffer + total, 1, capacity - total, s_export_file);
        total += count;
        if (count == 0 || feof(s_export_file)) {
            fclose(s_export_file);
            s_export_file = NULL;
        }
        if (count > 0) break;
    }
    xSemaphoreGive(s_lock);
    return total;
}

void offline_store_export_close(void)
{
    if (!s_lock) return;
    xSemaphoreTake(s_lock, portMAX_DELAY);
    export_close_locked();
    xSemaphoreGive(s_lock);
}
