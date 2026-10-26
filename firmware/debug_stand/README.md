# Промежуточный стенд: один микрофон

Прошивка для отладки оборудования, у которого пока один I2S-микрофон и карта SD. Это не каркас четырёх каналов и не прогон NN1 на ESP32-S3.

Поток режется скользящим окном из `config/window_config.yaml`:

- длина окна 2.5 с, 44.1 кГц, 16 бит, один канал;
- шаг нарезки — базовый hop инференса 1.0 с (`CUT_HOP_SAMPLES`, по умолчанию 44100 отсчётов);
- внутри окна спектрограмма: FFT 1024, hop 512, Hann, log-mel, 128 полос, как `ml/generate_spectrograms.py`.

Тишина не выбрасывается: на отладке нулевой файл — это признак мёртвого микрофона. RMS пишется в заголовок и в `windows.csv`.

`config/window_config.yaml` эта прошивка не меняет.

## Что появляется на карте

Каждое включение создаёт новый каталог `/sdcard/debug/0001`, `0002`, …

| Файл | Содержание |
|---|---|
| `wNNNNNN.wav` | ровно 2.5 с, моно, 16 бит, 44.1 кГц |
| `wNNNNNN.lmel` | log-mel, 128 полос × 216 кадров, float32 |
| `windows.csv` | индекс, `start_sample`, RMS, время расчёта |

Заголовок `.lmel` — 36 байт, little-endian: `LMEL`, версия, каналы, sample rate, длина окна, шаг нарезки, `start_sample`, FFT, hop, n_mels, n_frames, RMS. Дальше матрица `mel * 216 + frame`.

Кадр спектрограммы центрирован, как в librosa: первый отсчёт кадра `i` лежит на `i * 512 - 512`, край дополнен нулями.

## Сборка

ESP-IDF 5.1+, цель ESP32-S3. В menuconfig включить PSRAM той платы, которая стоит на стенде. Кольцо и спектрограмма занимают около 1 МБ.

```text
cd firmware/debug_stand
idf.py set-target esp32s3
idf.py build flash monitor
```

Пины — в `main/board_pins.h`. На модуле N16R8 не занимать GPIO 26–37. Микрофон ICS-43434: вывод L/R на землю. На осциллографе BCLK около 2.8224 МГц. Если WAV почти нулевой, сначала проверить L/R и `I2S_SLOT_INDEX`, затем `I2S_PCM_SHIFT`.

Шаг 2.0 с или 0.5 с: собрать с `-DCUT_HOP_SAMPLES=88200` или `-DCUT_HOP_SAMPLES=22050`.

## Проверка без платы

```text
python firmware/debug_stand/host/check_contract.py
python firmware/debug_stand/host/test_log_mel.py
```

Вторая команда режет синтетический WAV тем же кодом, что пойдёт на устройство, и сравнивает log-mel с librosa. Это не измерение на ESP32-S3.

| Параметр | Прошивка | `config/window_config.yaml` |
|---|---|---|
| Длина окна | 2.5 с | `window_length_sec: 2.5` |
| Частота дискретизации | 44.1 кГц | `sample_rate: 44100` |
| FFT | 1024 | `n_fft: 1024` |
| Hop спектрограммы | 512 | `hop_length: 512` |
| Оконная функция | Hann | `window_function: hann` |
| Представление | log-mel | `representation: log_mel` |
| Шаг нарезки | 1.0 с | `hop_inference_base_sec: 1.0` |
