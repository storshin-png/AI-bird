#include "board_pins.h"
#include "log_mel.h"
#include "slice.h"
#include "store.h"
#include "window_contract.h"

#include <inttypes.h>
#include <stdio.h>
#include <string.h>

#include "driver/i2s_std.h"
#include "driver/sdspi_host.h"
#include "driver/spi_common.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_vfs_fat.h"
#include "freertos/FreeRTOS.h"
#include "sdmmc_cmd.h"

static const char *TAG = "debug_spec";

static const size_t RING_SAMPLES = (size_t)WINDOW_SAMPLES + (size_t)CUT_HOP_SAMPLES * 4;

static void *alloc_buffer(size_t bytes)
{
    void *ptr = heap_caps_malloc(bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!ptr) {
        ptr = heap_caps_malloc(bytes, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    }
    return ptr;
}

static int mount_sd(void)
{
    sdmmc_card_t *card = NULL;
    sdmmc_host_t host = SDSPI_HOST_DEFAULT();
    esp_vfs_fat_sdmmc_mount_config_t mount = {
        .format_if_mount_failed = false,
        .max_files = 5,
        .allocation_unit_size = 16 * 1024,
    };
    spi_bus_config_t bus = {
        .mosi_io_num = DBG_SD_MOSI,
        .miso_io_num = DBG_SD_MISO,
        .sclk_io_num = DBG_SD_SCK,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
        .max_transfer_sz = 4096,
    };
    sdspi_device_config_t slot = SDSPI_DEVICE_CONFIG_DEFAULT();
    esp_err_t err;

    host.slot = SPI2_HOST;
    err = spi_bus_initialize(SPI2_HOST, &bus, SPI_DMA_CH_AUTO);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "SPI SD: %s", esp_err_to_name(err));
        return -1;
    }
    slot.gpio_cs = DBG_SD_CS;
    slot.host_id = SPI2_HOST;
    err = esp_vfs_fat_sdspi_mount("/sdcard", &host, &slot, &mount, &card);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "карта не смонтирована: %s", esp_err_to_name(err));
        return -1;
    }
    sdmmc_card_print_info(stdout, card);
    return 0;
}

static int start_i2s(i2s_chan_handle_t *rx)
{
    i2s_chan_config_t channel = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_AUTO, I2S_ROLE_MASTER);
    i2s_std_config_t standard = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(SAMPLE_RATE),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = DBG_I2S_BCLK,
            .ws = DBG_I2S_WS,
            .dout = I2S_GPIO_UNUSED,
            .din = DBG_I2S_DIN,
            .invert_flags = {
                .mclk_inv = false,
                .bclk_inv = false,
                .ws_inv = false,
            },
        },
    };
    esp_err_t err;

    channel.dma_desc_num = 16;
    channel.dma_frame_num = 512;
    err = i2s_new_channel(&channel, NULL, rx);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "I2S канал: %s", esp_err_to_name(err));
        return -1;
    }
    err = i2s_channel_init_std_mode(*rx, &standard);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "I2S режим: %s", esp_err_to_name(err));
        return -1;
    }
    err = i2s_channel_enable(*rx);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "I2S пуск: %s", esp_err_to_name(err));
        return -1;
    }
    return 0;
}

static void skip_overwritten(const AudioRing *ring, uint64_t *start)
{
    size_t capacity = ring_capacity(ring);
    uint64_t total = ring_total(ring);
    uint64_t oldest;
    uint64_t behind;
    uint64_t steps;

    if (total < capacity) {
        return;
    }
    oldest = total - capacity;
    if (*start >= oldest) {
        return;
    }
    behind = oldest - *start;
    steps = (behind + (uint64_t)CUT_HOP_SAMPLES - 1) / (uint64_t)CUT_HOP_SAMPLES;
    *start += steps * (uint64_t)CUT_HOP_SAMPLES;
    ESP_LOGW(TAG, "кольцо затёрло окна: %" PRIu64 ", следующий start=%" PRIu64, steps, *start);
}

void app_main(void)
{
    i2s_chan_handle_t rx = NULL;
    AudioRing *ring = NULL;
    LogMel *mel = NULL;
    int16_t *window = NULL;
    float *spec = NULL;
    uint64_t start = 0;
    uint32_t index = 1;

    ESP_LOGI(
        TAG,
        "один микрофон, окно 2.5 с, %d Гц, FFT %d, hop %d, Hann, log-mel, шаг нарезки %d",
        SAMPLE_RATE,
        N_FFT,
        HOP_LENGTH,
        CUT_HOP_SAMPLES);

    if (mount_sd() != 0 || store_open("/sdcard/debug") != 0) {
        ESP_LOGE(TAG, "SD не готова");
        return;
    }
    ESP_LOGI(TAG, "сессия %s", store_dir());

    if (log_mel_init(&mel) != 0) {
        ESP_LOGE(TAG, "не собрать mel-фильтр");
        return;
    }
    {
        int16_t *storage = alloc_buffer(RING_SAMPLES * sizeof(int16_t));
        if (!storage || ring_init(&ring, storage, RING_SAMPLES) != 0) {
            ESP_LOGE(TAG, "нет %u байт под кольцо, включите PSRAM", (unsigned)(RING_SAMPLES * sizeof(int16_t)));
            log_mel_free(mel);
            return;
        }
    }
    window = alloc_buffer(WINDOW_SAMPLES * sizeof(int16_t));
    spec = alloc_buffer((size_t)N_MELS * (size_t)N_FRAMES * sizeof(float));
    if (!window || !spec) {
        ESP_LOGE(TAG, "нет буфера окна или спектрограммы, включите PSRAM");
        return;
    }
    if (start_i2s(&rx) != 0) {
        return;
    }

    while (1) {
        int32_t raw[256];
        int16_t pcm[128];
        size_t bytes = 0;
        size_t frames;
        size_t i;
        esp_err_t err = i2s_channel_read(rx, raw, sizeof raw, &bytes, portMAX_DELAY);
        if (err != ESP_OK || bytes < 8) {
            ESP_LOGE(TAG, "чтение I2S: %s", esp_err_to_name(err));
            continue;
        }
        frames = bytes / (2 * sizeof(int32_t));
        for (i = 0; i < frames; i++) {
            pcm[i] = (int16_t)(raw[i * 2 + I2S_SLOT_INDEX] >> I2S_PCM_SHIFT);
        }
        ring_push(ring, pcm, frames);
        skip_overwritten(ring, &start);

        while (window_ready(ring_total(ring), start, WINDOW_SAMPLES)) {
            WindowMeta meta;
            int64_t t0;
            if (start > UINT32_MAX) {
                ESP_LOGE(TAG, "сессия длиннее поля start_sample");
                return;
            }
            if (ring_copy(ring, start, window, WINDOW_SAMPLES) != 0) {
                ESP_LOGW(TAG, "окно start=%" PRIu64 " уже затёрто", start);
                start += CUT_HOP_SAMPLES;
                continue;
            }
            t0 = esp_timer_get_time();
            if (log_mel_compute(mel, window, WINDOW_SAMPLES, spec) != 0) {
                ESP_LOGE(TAG, "сбой спектрограммы");
                return;
            }
            meta.index = index;
            meta.start_sample = (uint32_t)start;
            meta.hop_samples = CUT_HOP_SAMPLES;
            meta.rms = pcm_rms(window, WINDOW_SAMPLES);
            meta.compute_ms = (int32_t)((esp_timer_get_time() - t0) / 1000);
            if (store_write_window(
                    &meta,
                    window,
                    WINDOW_SAMPLES,
                    spec,
                    (size_t)N_MELS * (size_t)N_FRAMES) != 0) {
                ESP_LOGE(TAG, "запись на SD остановилась");
                return;
            }
            ESP_LOGI(
                TAG,
                "окно %u start=%u rms=%.5f %d мс",
                meta.index,
                meta.start_sample,
                meta.rms,
                meta.compute_ms);
            start += CUT_HOP_SAMPLES;
            index++;
        }
    }
}
