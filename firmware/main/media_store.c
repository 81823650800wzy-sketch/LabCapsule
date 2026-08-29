#include "media_store.h"

#include <errno.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

#define MEDIA_CURRENT_PATH "/offline/current.lcg"
/* The production FAT volume intentionally uses short 8.3 filenames. */
#define MEDIA_TEMP_PATH "/offline/currtmp.lcg"
#define MEDIA_BACKUP_PATH "/offline/currbak.lcg"
#define MEDIA_CLIP_MAGIC 0x4C434734U
#define MEDIA_CLIP_VERSION 1U
#define MEDIA_MAX_FRAMES 600U

static const char *TAG = "MediaStore";
static SemaphoreHandle_t s_lock;
static FILE *s_upload;
static size_t s_expected;
static size_t s_received;
static size_t s_clip_size;
static bool s_available;

static uint16_t read_be16(const uint8_t *value)
{
    return (uint16_t)(((uint16_t)value[0] << 8) | value[1]);
}

static uint32_t read_be32(const uint8_t *value)
{
    return ((uint32_t)value[0] << 24) | ((uint32_t)value[1] << 16) |
           ((uint32_t)value[2] << 8) | value[3];
}

static bool read_exact(FILE *file, void *buffer, size_t length)
{
    return file && buffer && fread(buffer, 1, length, file) == length;
}

static bool read_frame_header(FILE *file, media_store_frame_t *frame)
{
    uint8_t raw[13];
    if (!read_exact(file, raw, sizeof(raw))) return false;
    if (raw[0] == 1) frame->encoding = LABCAPSULE_MEDIA_RGB332;
    else if (raw[0] == 2) frame->encoding = LABCAPSULE_MEDIA_RLE332;
    else if (raw[0] == 3) frame->encoding = LABCAPSULE_MEDIA_DELTA332;
    else frame->encoding = LABCAPSULE_MEDIA_RGB332;
    frame->x = read_be16(raw + 1);
    frame->y = read_be16(raw + 3);
    frame->width = read_be16(raw + 5);
    frame->height = read_be16(raw + 7);
    frame->payload_size = read_be32(raw + 9);
    if (frame->payload_size == 0)
        return frame->width == 0 && frame->height == 0;
    return frame->width > 0 && frame->height > 0 &&
           (uint32_t)frame->x + frame->width <= 240U &&
           (uint32_t)frame->y + frame->height <= 320U &&
           frame->payload_size <= 153600U;
}

static bool validate_file(const char *path, size_t *size_out)
{
    FILE *file = fopen(path, "rb");
    if (!file) return false;
    uint8_t header[16];
    bool valid = read_exact(file, header, sizeof(header)) &&
            read_be32(header) == MEDIA_CLIP_MAGIC &&
            read_be32(header + 4) == MEDIA_CLIP_VERSION;
    uint32_t interval = valid ? read_be32(header + 8) : 0;
    uint32_t loop_frames = valid ? read_be32(header + 12) : 0;
    valid = valid && interval >= 20 && interval <= 2000 &&
            loop_frames > 0 && loop_frames <= MEDIA_MAX_FRAMES;
    media_store_frame_t frame;
    for (uint32_t index = 0; valid && index <= loop_frames; ++index) {
        valid = read_frame_header(file, &frame);
        if (valid && fseek(file, (long)frame.payload_size, SEEK_CUR) != 0) valid = false;
    }
    long position = valid ? ftell(file) : -1;
    if (valid && fseek(file, 0, SEEK_END) == 0) {
        long end = ftell(file);
        valid = position >= 0 && end == position && end <= (long)MEDIA_STORE_MAX_CLIP_BYTES;
        if (valid && size_out) *size_out = (size_t)end;
    } else valid = false;
    fclose(file);
    return valid;
}

esp_err_t media_store_init(void)
{
    s_lock = xSemaphoreCreateMutex();
    if (!s_lock) return ESP_ERR_NO_MEM;
    unlink(MEDIA_TEMP_PATH);
    if (access(MEDIA_CURRENT_PATH, F_OK) != 0 && access(MEDIA_BACKUP_PATH, F_OK) == 0)
        rename(MEDIA_BACKUP_PATH, MEDIA_CURRENT_PATH);
    else unlink(MEDIA_BACKUP_PATH);
    s_available = validate_file(MEDIA_CURRENT_PATH, &s_clip_size);
    if (!s_available && access(MEDIA_CURRENT_PATH, F_OK) == 0) unlink(MEDIA_CURRENT_PATH);
    ESP_LOGI(TAG, "Current clip %s (%u bytes)", s_available ? "ready" : "empty",
             (unsigned)s_clip_size);
    return ESP_OK;
}

bool media_store_clip_available(void)
{
    bool available;
    if (s_lock) xSemaphoreTake(s_lock, portMAX_DELAY);
    available = s_available;
    if (s_lock) xSemaphoreGive(s_lock);
    return available;
}

size_t media_store_clip_size(void)
{
    size_t size;
    if (s_lock) xSemaphoreTake(s_lock, portMAX_DELAY);
    size = s_clip_size;
    if (s_lock) xSemaphoreGive(s_lock);
    return size;
}

esp_err_t media_store_upload_begin(size_t expected_size)
{
    if (!s_lock || expected_size < 29 || expected_size > MEDIA_STORE_MAX_CLIP_BYTES)
        return ESP_ERR_INVALID_SIZE;
    xSemaphoreTake(s_lock, portMAX_DELAY);
    if (s_upload) {
        xSemaphoreGive(s_lock);
        return ESP_ERR_INVALID_STATE;
    }
    unlink(MEDIA_TEMP_PATH);
    s_upload = fopen(MEDIA_TEMP_PATH, "w+b");
    if (!s_upload) {
        ESP_LOGE(TAG, "Temporary clip open failed: errno=%d", errno);
        xSemaphoreGive(s_lock);
        return ESP_FAIL;
    }
    setvbuf(s_upload, NULL, _IOFBF, 16384);
    s_expected = expected_size;
    s_received = 0;
    xSemaphoreGive(s_lock);
    return ESP_OK;
}

esp_err_t media_store_upload_write(const uint8_t *data, size_t length)
{
    if (!s_lock || !data || length == 0) return ESP_ERR_INVALID_ARG;
    xSemaphoreTake(s_lock, portMAX_DELAY);
    esp_err_t result = ESP_OK;
    if (!s_upload || s_received + length > s_expected ||
        fwrite(data, 1, length, s_upload) != length) result = ESP_FAIL;
    else s_received += length;
    xSemaphoreGive(s_lock);
    return result;
}

esp_err_t media_store_upload_finish(void)
{
    if (!s_lock) return ESP_ERR_INVALID_STATE;
    xSemaphoreTake(s_lock, portMAX_DELAY);
    if (!s_upload || s_received != s_expected) {
        if (s_upload) fclose(s_upload);
        s_upload = NULL;
        unlink(MEDIA_TEMP_PATH);
        xSemaphoreGive(s_lock);
        return ESP_ERR_INVALID_SIZE;
    }
    fflush(s_upload);
    fclose(s_upload);
    s_upload = NULL;
    size_t validated_size = 0;
    if (!validate_file(MEDIA_TEMP_PATH, &validated_size)) {
        unlink(MEDIA_TEMP_PATH);
        xSemaphoreGive(s_lock);
        return ESP_ERR_INVALID_ARG;
    }
    unlink(MEDIA_BACKUP_PATH);
    if (s_available && rename(MEDIA_CURRENT_PATH, MEDIA_BACKUP_PATH) != 0) {
        unlink(MEDIA_TEMP_PATH);
        xSemaphoreGive(s_lock);
        return ESP_FAIL;
    }
    if (rename(MEDIA_TEMP_PATH, MEDIA_CURRENT_PATH) != 0) {
        rename(MEDIA_BACKUP_PATH, MEDIA_CURRENT_PATH);
        xSemaphoreGive(s_lock);
        return ESP_FAIL;
    }
    unlink(MEDIA_BACKUP_PATH);
    s_available = true;
    s_clip_size = validated_size;
    s_expected = s_received = 0;
    xSemaphoreGive(s_lock);
    ESP_LOGI(TAG, "Current clip replaced atomically (%u bytes)", (unsigned)validated_size);
    return ESP_OK;
}

void media_store_upload_abort(void)
{
    if (!s_lock) return;
    xSemaphoreTake(s_lock, portMAX_DELAY);
    if (s_upload) fclose(s_upload);
    s_upload = NULL;
    s_expected = s_received = 0;
    unlink(MEDIA_TEMP_PATH);
    xSemaphoreGive(s_lock);
}

esp_err_t media_store_delete_clip(void)
{
    if (!s_lock) return ESP_ERR_INVALID_STATE;
    media_store_upload_abort();
    xSemaphoreTake(s_lock, portMAX_DELAY);
    int result = unlink(MEDIA_CURRENT_PATH);
    int unlink_error = errno;
    unlink(MEDIA_BACKUP_PATH);
    s_available = false;
    s_clip_size = 0;
    xSemaphoreGive(s_lock);
    return result == 0 || unlink_error == ENOENT ? ESP_OK : ESP_FAIL;
}

esp_err_t media_store_reader_open(media_store_reader_t *reader)
{
    if (!reader || !media_store_clip_available()) return ESP_ERR_NOT_FOUND;
    memset(reader, 0, sizeof(*reader));
    reader->file = fopen(MEDIA_CURRENT_PATH, "rb");
    if (!reader->file) return ESP_FAIL;
    uint8_t header[16];
    if (!read_exact(reader->file, header, sizeof(header)) ||
        read_be32(header) != MEDIA_CLIP_MAGIC ||
        read_be32(header + 4) != MEDIA_CLIP_VERSION) {
        media_store_reader_close(reader);
        return ESP_ERR_INVALID_ARG;
    }
    reader->interval_ms = read_be32(header + 8);
    reader->loop_frame_count = read_be32(header + 12);
    reader->file_size = media_store_clip_size();
    return ESP_OK;
}

static esp_err_t reader_frame(media_store_reader_t *reader, media_store_frame_t *frame,
                              uint8_t *payload, size_t capacity)
{
    if (!reader || !reader->file || !frame || !payload ||
        !read_frame_header(reader->file, frame) || frame->payload_size > capacity)
        return ESP_ERR_INVALID_SIZE;
    if (frame->payload_size > 0 &&
        fread(payload, 1, frame->payload_size, reader->file) != frame->payload_size)
        return ESP_FAIL;
    return ESP_OK;
}

esp_err_t media_store_reader_bootstrap(media_store_reader_t *reader,
                                       media_store_frame_t *frame,
                                       uint8_t *payload, size_t capacity)
{
    esp_err_t result = reader_frame(reader, frame, payload, capacity);
    if (result == ESP_OK) reader->loop_offset = ftell(reader->file);
    return result;
}

esp_err_t media_store_reader_next(media_store_reader_t *reader,
                                  media_store_frame_t *frame,
                                  uint8_t *payload, size_t capacity)
{
    if (!reader || !reader->file || reader->loop_offset <= 0) return ESP_ERR_INVALID_STATE;
    if (reader->loop_index >= reader->loop_frame_count) {
        if (fseek(reader->file, reader->loop_offset, SEEK_SET) != 0) return ESP_FAIL;
        reader->loop_index = 0;
    }
    esp_err_t result = reader_frame(reader, frame, payload, capacity);
    if (result == ESP_OK) ++reader->loop_index;
    return result;
}

void media_store_reader_close(media_store_reader_t *reader)
{
    if (!reader) return;
    if (reader->file) fclose(reader->file);
    memset(reader, 0, sizeof(*reader));
}
