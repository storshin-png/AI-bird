#include "store.h"

#include "slice.h"
#include "window_contract.h"

#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>

#if defined(_WIN32)
#include <direct.h>
static int make_dir(const char *path)
{
    return _mkdir(path);
}
#else
static int make_dir(const char *path)
{
    return mkdir(path, 0775);
}
#endif

static char g_dir[160];

static int ensure_dir(const char *path)
{
    if (make_dir(path) == 0 || errno == EEXIST) {
        return 0;
    }
    return -1;
}

static void write_u16(unsigned char *dst, uint16_t value)
{
    dst[0] = (unsigned char)(value & 0xff);
    dst[1] = (unsigned char)((value >> 8) & 0xff);
}

static void write_u32(unsigned char *dst, uint32_t value)
{
    dst[0] = (unsigned char)(value & 0xff);
    dst[1] = (unsigned char)((value >> 8) & 0xff);
    dst[2] = (unsigned char)((value >> 16) & 0xff);
    dst[3] = (unsigned char)((value >> 24) & 0xff);
}

static int write_wav(const char *path, const int16_t *pcm, size_t count)
{
    unsigned char header[44];
    uint32_t data_bytes = (uint32_t)count * 2u;
    FILE *file;
    size_t wrote;

    memset(header, 0, sizeof header);
    memcpy(header, "RIFF", 4);
    write_u32(header + 4, 36u + data_bytes);
    memcpy(header + 8, "WAVE", 4);
    memcpy(header + 12, "fmt ", 4);
    write_u32(header + 16, 16);
    write_u16(header + 20, 1);
    write_u16(header + 22, DEBUG_CHANNELS);
    write_u32(header + 24, SAMPLE_RATE);
    write_u32(header + 28, SAMPLE_RATE * DEBUG_CHANNELS * 2u);
    write_u16(header + 32, DEBUG_CHANNELS * 2u);
    write_u16(header + 34, 16);
    memcpy(header + 36, "data", 4);
    write_u32(header + 40, data_bytes);

    file = fopen(path, "wb");
    if (!file) {
        return -1;
    }
    wrote = fwrite(header, 1, sizeof header, file);
    if (wrote == sizeof header) {
        wrote = fwrite(pcm, sizeof(int16_t), count, file);
    } else {
        wrote = 0;
    }
    if (fclose(file) != 0 || wrote != count) {
        return -1;
    }
    return 0;
}

static int write_lmel(const char *path, const WindowMeta *meta, float rms, const float *spec, size_t spec_count)
{
    LmelHeader header;
    FILE *file;
    size_t wrote;

    memset(&header, 0, sizeof header);
    memcpy(header.magic, LMEL_MAGIC, 4);
    header.version = LMEL_VERSION;
    header.channels = DEBUG_CHANNELS;
    header.sample_rate = SAMPLE_RATE;
    header.window_samples = WINDOW_SAMPLES;
    header.hop_samples = meta->hop_samples;
    header.start_sample = meta->start_sample;
    header.n_fft = N_FFT;
    header.hop_length = HOP_LENGTH;
    header.n_mels = N_MELS;
    header.n_frames = N_FRAMES;
    header.rms = rms;

    file = fopen(path, "wb");
    if (!file) {
        return -1;
    }
    wrote = fwrite(&header, 1, sizeof header, file);
    if (wrote == sizeof header) {
        wrote = fwrite(spec, sizeof(float), spec_count, file);
    } else {
        wrote = 0;
    }
    if (fclose(file) != 0 || wrote != spec_count) {
        return -1;
    }
    return 0;
}

static int append_csv(const WindowMeta *meta, float rms)
{
    char path[180];
    FILE *file;
    int fresh;
    int written;

    written = snprintf(path, sizeof path, "%s/windows.csv", g_dir);
    if (written < 0 || (size_t)written >= sizeof path) {
        return -1;
    }
    fresh = 0;
    file = fopen(path, "rb");
    if (!file) {
        fresh = 1;
    } else {
        fclose(file);
    }
    file = fopen(path, "ab");
    if (!file) {
        return -1;
    }
    if (fresh) {
        fputs("index,start_sample,duration_sec,rms,wav_file,lmel_file,compute_ms\n", file);
    }
    fprintf(
        file,
        "%u,%u,2.5,%.6f,w%06u.wav,w%06u.lmel,%d\n",
        meta->index,
        meta->start_sample,
        rms,
        meta->index,
        meta->index,
        meta->compute_ms);
    if (fclose(file) != 0) {
        return -1;
    }
    return 0;
}

int store_open(const char *root)
{
    int session;

    if (!root || root[0] == '\0') {
        return -1;
    }
    if (ensure_dir(root) != 0) {
        return -1;
    }
    for (session = 1; session < 10000; session++) {
        struct stat st;
        int written = snprintf(g_dir, sizeof g_dir, "%s/%04d", root, session);
        if (written < 0 || (size_t)written >= sizeof g_dir) {
            return -1;
        }
        if (stat(g_dir, &st) != 0) {
            return ensure_dir(g_dir);
        }
    }
    return -1;
}

int store_write_window(
    const WindowMeta *meta,
    const int16_t *pcm,
    size_t pcm_count,
    const float *spec,
    size_t spec_count)
{
    char wav_path[180];
    char lmel_path[180];
    int written;
    float rms;

    if (!meta || !pcm || !spec || g_dir[0] == '\0') {
        return -1;
    }
    if (pcm_count != WINDOW_SAMPLES || spec_count != (size_t)N_MELS * (size_t)N_FRAMES) {
        return -1;
    }
    written = snprintf(wav_path, sizeof wav_path, "%s/w%06u.wav", g_dir, meta->index);
    if (written < 0 || (size_t)written >= sizeof wav_path) {
        return -1;
    }
    written = snprintf(lmel_path, sizeof lmel_path, "%s/w%06u.lmel", g_dir, meta->index);
    if (written < 0 || (size_t)written >= sizeof lmel_path) {
        return -1;
    }

    rms = pcm_rms(pcm, pcm_count);
    if (write_wav(wav_path, pcm, pcm_count) != 0) {
        return -1;
    }
    if (write_lmel(lmel_path, meta, rms, spec, spec_count) != 0) {
        return -1;
    }
    return append_csv(meta, rms);
}

const char *store_dir(void)
{
    return g_dir;
}
