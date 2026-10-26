#ifndef WINDOW_CONTRACT_H
#define WINDOW_CONTRACT_H

/*
 * Цифры единого окна. Источник — config/window_config.yaml.
 * Прошивка этот файл не меняет. Сверка: host/check_contract.py.
 * n_mels в контракт окна не входит: 128, как MEL_BANDS в ml/generate_spectrograms.py.
 */

#define SAMPLE_RATE 44100
#define N_FFT 1024
#define HOP_LENGTH 512
#define FREQ_MAX 22050
#define WINDOW_SAMPLES 110250
#define HOP_INFERENCE_BASE_SAMPLES 44100
#define HOP_INFERENCE_ADAPTIVE_SAMPLES 88200
#define HOP_INFERENCE_HIGH_SAMPLES 22050
#define N_MELS 128
#define N_FRAMES (1 + (WINDOW_SAMPLES) / (HOP_LENGTH))
#define DEBUG_CHANNELS 1

#define WINDOW_FUNCTION_NAME "hann"
#define REPRESENTATION_NAME "log_mel"

#ifndef CUT_HOP_SAMPLES
#define CUT_HOP_SAMPLES HOP_INFERENCE_BASE_SAMPLES
#endif

#define CONTRACT_ASSERT_1(cond, line) typedef char contract_assert_##line[(cond) ? 1 : -1]
#define CONTRACT_ASSERT_0(cond, line) CONTRACT_ASSERT_1(cond, line)
#define CONTRACT_STATIC_ASSERT(cond, msg) CONTRACT_ASSERT_0(cond, __LINE__)

CONTRACT_STATIC_ASSERT((WINDOW_SAMPLES) == (5 * (SAMPLE_RATE)) / 2, "window 2.5s");
CONTRACT_STATIC_ASSERT((HOP_INFERENCE_BASE_SAMPLES) == (SAMPLE_RATE), "base hop 1.0s");
CONTRACT_STATIC_ASSERT((HOP_INFERENCE_ADAPTIVE_SAMPLES) == 2 * (SAMPLE_RATE), "adaptive hop 2.0s");
CONTRACT_STATIC_ASSERT((HOP_INFERENCE_HIGH_SAMPLES) == (SAMPLE_RATE) / 2, "hop 0.5s");
CONTRACT_STATIC_ASSERT((N_FFT) == 1024, "n_fft");
CONTRACT_STATIC_ASSERT((HOP_LENGTH) == 512, "spectrogram hop");
CONTRACT_STATIC_ASSERT((FREQ_MAX) == (SAMPLE_RATE) / 2, "freq_max");
CONTRACT_STATIC_ASSERT((N_MELS) == 128, "n_mels");
CONTRACT_STATIC_ASSERT((N_FRAMES) == 216, "log-mel frames");
CONTRACT_STATIC_ASSERT((CUT_HOP_SAMPLES) > 0, "cut hop");
CONTRACT_STATIC_ASSERT((CUT_HOP_SAMPLES) <= (WINDOW_SAMPLES), "cut hop within window");

#endif
