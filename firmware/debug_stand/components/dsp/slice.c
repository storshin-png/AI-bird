#include "slice.h"

#include <math.h>
#include <stdlib.h>

struct AudioRing {
    int16_t *samples;
    size_t capacity;
    uint64_t total;
};

int ring_init(AudioRing **out, int16_t *storage, size_t capacity)
{
    AudioRing *ring;

    if (!out || !storage || capacity == 0) {
        return -1;
    }
    *out = NULL;
    ring = calloc(1, sizeof(*ring));
    if (!ring) {
        return -1;
    }
    ring->samples = storage;
    ring->capacity = capacity;
    *out = ring;
    return 0;
}

void ring_free(AudioRing *ring)
{
    free(ring);
}

void ring_push(AudioRing *ring, const int16_t *src, size_t count)
{
    size_t i;

    if (!ring || !src) {
        return;
    }
    for (i = 0; i < count; i++) {
        ring->samples[(size_t)(ring->total % ring->capacity)] = src[i];
        ring->total++;
    }
}

int ring_copy(const AudioRing *ring, uint64_t start, int16_t *dst, size_t count)
{
    size_t i;
    size_t offset;

    if (!ring || !dst || count == 0) {
        return -1;
    }
    if (start + (uint64_t)count > ring->total) {
        return -1;
    }
    if (ring->total - start > ring->capacity) {
        return -1;
    }
    offset = (size_t)(start % ring->capacity);
    for (i = 0; i < count; i++) {
        dst[i] = ring->samples[(offset + i) % ring->capacity];
    }
    return 0;
}

uint64_t ring_total(const AudioRing *ring)
{
    return ring ? ring->total : 0;
}

size_t ring_capacity(const AudioRing *ring)
{
    return ring ? ring->capacity : 0;
}

int window_ready(uint64_t total, uint64_t start, size_t window_samples)
{
    return start + (uint64_t)window_samples <= total;
}

float pcm_rms(const int16_t *pcm, size_t count)
{
    double acc = 0.0;
    size_t i;

    if (!pcm || count == 0) {
        return 0.0f;
    }
    for (i = 0; i < count; i++) {
        double x = (double)pcm[i] / 32768.0;
        acc += x * x;
    }
    return (float)sqrt(acc / (double)count);
}
