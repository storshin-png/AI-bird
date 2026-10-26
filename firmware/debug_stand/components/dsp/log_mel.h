#ifndef LOG_MEL_H
#define LOG_MEL_H

#include <stddef.h>
#include <stdint.h>

typedef struct LogMel LogMel;

int log_mel_init(LogMel **out);
void log_mel_free(LogMel *state);
int log_mel_compute(LogMel *state, const int16_t *pcm, size_t n_samples, float *out);

#endif
