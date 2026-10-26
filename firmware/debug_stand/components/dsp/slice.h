#ifndef SLICE_H
#define SLICE_H

#include <stddef.h>
#include <stdint.h>

typedef struct AudioRing AudioRing;

/* storage принадлежит вызывающему коду и живёт не короче кольца. */
int ring_init(AudioRing **out, int16_t *storage, size_t capacity);
void ring_free(AudioRing *ring);
void ring_push(AudioRing *ring, const int16_t *src, size_t count);
int ring_copy(const AudioRing *ring, uint64_t start, int16_t *dst, size_t count);
uint64_t ring_total(const AudioRing *ring);
size_t ring_capacity(const AudioRing *ring);

/* Окно [start, start + window_samples) готово, когда весь отрезок уже в потоке. */
int window_ready(uint64_t total, uint64_t start, size_t window_samples);

/* RMS по шкале [-1, 1], как у нарезки датасета: отсчёт / 32768. */
float pcm_rms(const int16_t *pcm, size_t count);

#endif
