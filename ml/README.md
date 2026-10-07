# Данные и модели

Скрипты нарезки, спектрограмм и проверки читают окно анализа из `config/window_config.yaml`. Длина фрагмента, sample rate, FFT, hop, оконная функция и представление берутся из этого файла.

Вход и выход задаются аргументами командной строки.

Нарезка открытых архивов остаётся моно: файл не из 4 каналов сводится в один канал. У записи с 4 каналами каналы сохраняются в одном wav. Смешение четырёх каналов в один — только с флагом `--mix-channels`.

Локальное окружение остаётся в `Python/venv/` и в репозиторий не входит.

Зависимости: `requirements.txt`.

Аудиофайлы из `Sound sample/` в репозиторий не коммитятся, пока CEO не закроет лицензии в журнале `doc_v2/IMPLEMENTATION_PLAN.md`.

## Пример

Из корня репозитория. Нарезка пишет `manifest_fragments.csv` в родительскую папку `--output`.

```text
python ml/cut_fragments.py --input data/raw --output data/fragments
python ml/generate_spectrograms.py --input data/fragments --output data/spectrograms --manifest data/manifest_fragments.csv
```

Свести 4 канала в моно перед нарезкой:

```text
python ml/cut_fragments.py --input data/field --output data/fragments --mix-channels
```
