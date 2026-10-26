#ifndef STORE_H
#define STORE_H

#include "window_contract.h"

#include <stddef.h>
#include <stdint.h>

#define LMEL_MAGIC "LMEL"
#define LMEL_VERSION 1

#pragma pack(push, 1)
typedef struct {
    char magic[4];
    uint16_t version;
    uint16_t channels;
    uint32_t sample_rate;
    uint32_t window_samples;
    uint32_t hop_samples;
    uint32_t start_sample;
    uint16_t n_fft;
    uint16_t hop_length;
    uint16_t n_mels;
    uint16_t n_frames;
    float rms;
} LmelHeader;
#pragma pack(pop)

CONTRACT_STATIC_ASSERT(sizeof(LmelHeader) == 36, "lmel header size");

typedef struct {
    uint32_t index;
    uint32_t start_sample;
    uint32_t hop_samples;
    float rms;
    int32_t compute_ms;
} WindowMeta;

/* Создаёт новый каталог сессии root/0001, root/0002, ... */
int store_open(const char *root);

/* Пишет wNNNNNN.wav, wNNNNNN.lmel и строку в windows.csv. */
int store_write_window(
    const WindowMeta *meta,
    const int16_t *pcm,
    size_t pcm_count,
    const float *spec,
    size_t spec_count);

const char *store_dir(void);

#endif
