#include "log_mel.h"

#include "window_contract.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

typedef struct {
    int bin;
    float weight;
} MelTap;

typedef struct {
    int begin;
    int count;
} MelRow;

struct LogMel {
    MelTap *taps;
    size_t tap_count;
    size_t tap_cap;
    MelRow rows[N_MELS];
    float *hann;
    float *re;
    float *im;
};

static double hz_to_mel(double hz)
{
    const double f_sp = 200.0 / 3.0;
    const double min_log_hz = 1000.0;
    const double min_log_mel = min_log_hz / f_sp;
    const double logstep = log(6.4) / 27.0;

    if (hz >= min_log_hz) {
        return min_log_mel + log(hz / min_log_hz) / logstep;
    }
    return hz / f_sp;
}

static double mel_to_hz(double mel)
{
    const double f_sp = 200.0 / 3.0;
    const double min_log_hz = 1000.0;
    const double min_log_mel = min_log_hz / f_sp;
    const double logstep = log(6.4) / 27.0;

    if (mel >= min_log_mel) {
        return min_log_hz * exp(logstep * (mel - min_log_mel));
    }
    return f_sp * mel;
}

static int append_tap(LogMel *state, int bin, float weight)
{
    if (state->tap_count == state->tap_cap) {
        size_t cap = state->tap_cap == 0 ? 2048 : state->tap_cap * 2;
        MelTap *grown = realloc(state->taps, cap * sizeof(MelTap));
        if (!grown) {
            return -1;
        }
        state->taps = grown;
        state->tap_cap = cap;
    }
    state->taps[state->tap_count].bin = bin;
    state->taps[state->tap_count].weight = weight;
    state->tap_count++;
    return 0;
}

static int build_mel(LogMel *state)
{
    const int n_points = N_MELS + 2;
    const int n_freq = N_FFT / 2 + 1;
    double *mel_f = calloc((size_t)n_points, sizeof(double));
    double *fft_f = calloc((size_t)n_freq, sizeof(double));
    double *fdiff = calloc((size_t)n_points - 1, sizeof(double));
    float *row = calloc((size_t)n_freq, sizeof(float));
    int failed = 0;

    if (!mel_f || !fft_f || !fdiff || !row) {
        failed = 1;
        goto done;
    }

    {
        double min_mel = hz_to_mel(0.0);
        double max_mel = hz_to_mel((double)FREQ_MAX);
        int i;
        for (i = 0; i < n_points; i++) {
            double mel = min_mel + (max_mel - min_mel) * (double)i / (double)(n_points - 1);
            mel_f[i] = mel_to_hz(mel);
        }
    }

    {
        int k;
        for (k = 0; k < n_freq; k++) {
            fft_f[k] = (double)k * (double)SAMPLE_RATE / (double)N_FFT;
        }
        for (k = 0; k < n_points - 1; k++) {
            fdiff[k] = mel_f[k + 1] - mel_f[k];
            if (fdiff[k] == 0.0) {
                failed = 1;
                goto done;
            }
        }
    }

    {
        int i;
        for (i = 0; i < N_MELS; i++) {
            int k;
            double enorm = 2.0 / (mel_f[i + 2] - mel_f[i]);
            state->rows[i].begin = (int)state->tap_count;
            state->rows[i].count = 0;
            for (k = 0; k < n_freq; k++) {
                double lower = -(mel_f[i] - fft_f[k]) / fdiff[i];
                double upper = (mel_f[i + 2] - fft_f[k]) / fdiff[i + 1];
                double tri = lower < upper ? lower : upper;
                float weight;
                if (tri < 0.0) {
                    tri = 0.0;
                }
                weight = (float)tri * (float)enorm;
                if (weight == 0.0f) {
                    continue;
                }
                if (append_tap(state, k, weight) != 0) {
                    failed = 1;
                    goto done;
                }
                state->rows[i].count++;
            }
        }
    }

done:
    free(mel_f);
    free(fft_f);
    free(fdiff);
    free(row);
    return failed ? -1 : 0;
}

static void fft_forward(float *re, float *im, int n)
{
    int i;
    int j = 0;

    for (i = 1; i < n; i++) {
        int bit = n >> 1;
        for (; j & bit; bit >>= 1) {
            j ^= bit;
        }
        j ^= bit;
        if (i < j) {
            float tr = re[i];
            float ti = im[i];
            re[i] = re[j];
            im[i] = im[j];
            re[j] = tr;
            im[j] = ti;
        }
    }

    for (i = 2; i <= n; i <<= 1) {
        int half = i >> 1;
        int block;
        for (block = 0; block < n; block += i) {
            int k;
            for (k = 0; k < half; k++) {
                int u = block + k;
                int v = u + half;
                double ang = -2.0 * M_PI * (double)k / (double)i;
                float w_re = (float)cos(ang);
                float w_im = (float)sin(ang);
                float vr = re[v] * w_re - im[v] * w_im;
                float vi = re[v] * w_im + im[v] * w_re;
                re[v] = re[u] - vr;
                im[v] = im[u] - vi;
                re[u] += vr;
                im[u] += vi;
            }
        }
    }
}

int log_mel_init(LogMel **out)
{
    LogMel *state;
    int n;

    if (!out) {
        return -1;
    }
    *out = NULL;
    state = calloc(1, sizeof(*state));
    if (!state) {
        return -1;
    }
    state->hann = calloc(N_FFT, sizeof(float));
    state->re = calloc(N_FFT, sizeof(float));
    state->im = calloc(N_FFT, sizeof(float));
    if (!state->hann || !state->re || !state->im || build_mel(state) != 0) {
        log_mel_free(state);
        return -1;
    }
    for (n = 0; n < N_FFT; n++) {
        state->hann[n] = 0.5f * (1.0f - (float)cos(2.0 * M_PI * (double)n / (double)N_FFT));
    }
    *out = state;
    return 0;
}

void log_mel_free(LogMel *state)
{
    if (!state) {
        return;
    }
    free(state->taps);
    free(state->hann);
    free(state->re);
    free(state->im);
    free(state);
}

int log_mel_compute(LogMel *state, const int16_t *pcm, size_t n_samples, float *out)
{
    const size_t count = (size_t)N_MELS * (size_t)N_FRAMES;
    const float amin = 1e-10f;
    float peak = 0.0f;
    float max_db = -1.0e30f;
    float floor_db;
    size_t i;
    int frame;

    if (!state || !pcm || !out || n_samples != WINDOW_SAMPLES) {
        return -1;
    }

    for (frame = 0; frame < N_FRAMES; frame++) {
        int64_t origin = (int64_t)frame * HOP_LENGTH - (N_FFT / 2);
        int mel;
        int k;

        for (k = 0; k < N_FFT; k++) {
            int64_t idx = origin + k;
            float sample = 0.0f;
            if (idx >= 0 && idx < (int64_t)n_samples) {
                sample = (float)pcm[idx] / 32768.0f;
            }
            state->re[k] = sample * state->hann[k];
            state->im[k] = 0.0f;
        }
        fft_forward(state->re, state->im, N_FFT);

        for (mel = 0; mel < N_MELS; mel++) {
            const MelRow *row = &state->rows[mel];
            float power = 0.0f;
            int t;
            for (t = 0; t < row->count; t++) {
                const MelTap *tap = &state->taps[row->begin + t];
                float re = state->re[tap->bin];
                float im = state->im[tap->bin];
                power += tap->weight * (re * re + im * im);
            }
            out[(size_t)mel * (size_t)N_FRAMES + (size_t)frame] = power;
            if (power > peak) {
                peak = power;
            }
        }
    }

    if (peak < amin) {
        peak = amin;
    }
    for (i = 0; i < count; i++) {
        float value = out[i] < amin ? amin : out[i];
        float db = 10.0f * (float)log10((double)value) - 10.0f * (float)log10((double)peak);
        out[i] = db;
        if (db > max_db) {
            max_db = db;
        }
    }
    floor_db = max_db - 80.0f;
    for (i = 0; i < count; i++) {
        if (out[i] < floor_db) {
            out[i] = floor_db;
        }
    }
    return 0;
}
