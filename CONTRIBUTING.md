# Как вносить изменения

Порядок ролей и мержа — в `doc_v2/COLLABORATION.md`. Общие команды — в `doc_v2/instructions/00_COMMON.md`.

1. Взять свежий `main` и создать ветку `<зона>/<короткая-задача>`.
2. Один пакет — один pull request в `main`.
3. Дождаться зелёной проверки `ci`.
4. Мерж делает CEO (`storshin-png`).

Прямой push в `main` не используется. Смена `config/window_config.yaml`, API или схемы БД идёт отдельным запросом с пометкой `contract`.
