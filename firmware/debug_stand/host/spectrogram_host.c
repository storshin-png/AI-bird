#include "log_mel.h"
#include "slice.h"
#include "store.h"
#include "window_contract.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static uint16_t read_u16(const unsigned char *p)
{
    return (uint16_t)(p[0] | (p[1] << 8));
}

static uint32_t read_u32(const unsigned char *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static int read_wav(const char *path, int16_t **out, size_t *count)
{
    FILE *file;
    unsigned char chunk[8];
    unsigned char fmt[16];
    uint32_t riff_size;
    uint16_t channels = 0;
    uint16_t bits = 0;
    uint32_t rate = 0;
    int have_fmt = 0;
    int16_t *pcm = NULL;

    file = fopen(path, "rb");
    if (!file) {
        fprintf(stderr, "не открыть %s\n", path);
        return -1;
    }
    if (fread(chunk, 1, 8, file) != 8 || memcmp(chunk, "RIFF", 4) != 0) {
        fprintf(stderr, "это не RIFF: %s\n", path);
        fclose(file);
        return -1;
    }
    riff_size = read_u32(chunk + 4);
    (void)riff_size;
    if (fread(chunk, 1, 4, file) != 4 || memcmp(chunk, "WAVE", 4) != 0) {
        fprintf(stderr, "это не WAVE: %s\n", path);
        fclose(file);
        return -1;
    }

    while (fread(chunk, 1, 8, file) == 8) {
        uint32_t size = read_u32(chunk + 4);
        if (memcmp(chunk, "fmt ", 4) == 0) {
            if (size < 16 || fread(fmt, 1, 16, file) != 16) {
                fprintf(stderr, "битый fmt\n");
                fclose(file);
                return -1;
            }
            if (size > 16 && fseek(file, (long)(size - 16), SEEK_CUR) != 0) {
                fclose(file);
                return -1;
            }
            if (read_u16(fmt) != 1) {
                fprintf(stderr, "нужен PCM\n");
                fclose(file);
                return -1;
            }
            channels = read_u16(fmt + 2);
            rate = read_u32(fmt + 4);
            bits = read_u16(fmt + 14);
            have_fmt = 1;
        } else if (memcmp(chunk, "data", 4) == 0) {
            size_t samples;
            if (!have_fmt || channels != 1 || bits != 16 || rate != SAMPLE_RATE) {
                fprintf(stderr, "нужен моно 16 бит %d Гц\n", SAMPLE_RATE);
                fclose(file);
                return -1;
            }
            if (size % 2u != 0) {
                fclose(file);
                return -1;
            }
            samples = size / 2u;
            pcm = malloc(samples * sizeof(int16_t));
            if (!pcm || fread(pcm, sizeof(int16_t), samples, file) != samples) {
                free(pcm);
                fclose(file);
                return -1;
            }
            fclose(file);
            *out = pcm;
            *count = samples;
            return 0;
        } else {
            if (fseek(file, (long)size, SEEK_CUR) != 0) {
                fclose(file);
                return -1;
            }
        }
        if (size & 1u) {
            if (fseek(file, 1, SEEK_CUR) != 0) {
                fclose(file);
                return -1;
            }
        }
    }

    free(pcm);
    fclose(file);
    fprintf(stderr, "в wav нет data\n");
    return -1;
}

int main(int argc, char **argv)
{
    int16_t *pcm = NULL;
    int16_t *window = NULL;
    float *spec = NULL;
    LogMel *mel = NULL;
    size_t count = 0;
    uint64_t start = 0;
    uint32_t index = 1;
    int windows = 0;

    if (argc != 3) {
        fprintf(stderr, "использование: spectrogram_host input.wav output_dir\n");
        return 2;
    }
    if (read_wav(argv[1], &pcm, &count) != 0) {
        return 1;
    }
    window = malloc(WINDOW_SAMPLES * sizeof(int16_t));
    spec = malloc((size_t)N_MELS * (size_t)N_FRAMES * sizeof(float));
    if (!window || !spec || log_mel_init(&mel) != 0 || store_open(argv[2]) != 0) {
        fprintf(stderr, "не подготовить спектрограмму или каталог\n");
        free(pcm);
        free(window);
        free(spec);
        log_mel_free(mel);
        return 1;
    }

    while (window_ready(count, start, WINDOW_SAMPLES)) {
        WindowMeta meta;
        if (start > UINT32_MAX) {
            fprintf(stderr, "start_sample не влезает в заголовок\n");
            break;
        }
        memcpy(window, pcm + (size_t)start, WINDOW_SAMPLES * sizeof(int16_t));
        if (log_mel_compute(mel, window, WINDOW_SAMPLES, spec) != 0) {
            fprintf(stderr, "сбой спектрограммы\n");
            free(pcm);
            free(window);
            free(spec);
            log_mel_free(mel);
            return 1;
        }
        meta.index = index;
        meta.start_sample = (uint32_t)start;
        meta.hop_samples = CUT_HOP_SAMPLES;
        meta.rms = pcm_rms(window, WINDOW_SAMPLES);
        meta.compute_ms = 0;
        if (store_write_window(&meta, window, WINDOW_SAMPLES, spec, (size_t)N_MELS * (size_t)N_FRAMES) != 0) {
            fprintf(stderr, "не записать окно %u\n", index);
            free(pcm);
            free(window);
            free(spec);
            log_mel_free(mel);
            return 1;
        }
        start += CUT_HOP_SAMPLES;
        index++;
        windows++;
    }

    printf("окон: %d\nкаталог: %s\n", windows, store_dir());
    free(pcm);
    free(window);
    free(spec);
    log_mel_free(mel);
    return windows > 0 ? 0 : 1;
}
