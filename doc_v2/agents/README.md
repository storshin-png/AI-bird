# Как отдавать ТЗ агенту

ТЗ в этой папке — задание для любого агента, в том числе стороннего. Человек вставляет в агента текст файла и разрешает читать только указанные там пути репозитория.

Агенты Cursor в этом репозитории лежат в `.cursor/skills/`. Руководитель проекта выдаёт им пакеты в `doc_v2/packets/`. Первый пакет ML уже выдан: `doc_v2/packets/ML-001.md`.

| Skill | Участник | ТЗ |
|---|---|---|
| `project-lead` | CEO | направление и пакеты |
| `auditor` | CEO | состояние GitHub, без правок |
| `advisor` | CEO | советы по организации работы |
| `ml-agent` | CEO | `03_ML.md` |
| `cto-agent` | KazakovDmitryS@gmail.com | `02_CTO.md` |
| `backend-agent` | krisstyushac@gmail.com | `04_BACKEND.md` |
| `gis-agent` | karimovad39@gmail.com | `06_GIS.md` |
| `ornithologist-agent` | olgatorshina7@gmail.com | `05_ORNITHOLOGIST.md` |
| `field-agent` | olgatorshina7@gmail.com | `07_FIELD.md` |

Агент пишет файлы в ветке пакета. В `main` он не мержит и приглашения в GitHub не рассылает. Если участник уже принёс ветку сторонним агентом, агент Cursor этой зоны сверяет diff с ТЗ и не пишет второе решение. Следующий пакет начинается после мержа текущего.

Общие границы для всякого агента:

- Рамка — `MVP_SPEC.md`. Функции из раздела «Что не входит в MVP» не делать.
- Цифры окна анализа брать из `config/window_config.yaml`. Файл не менять.
- API, схему БД и поля события не менять внутри обычного пакета.
- Секреты, сырое аудио, виртуальное окружение и файлы `~$*` не коммитить.
- Один пакет — одна ветка и один pull request.

| Файл | Кому отдавать |
|---|---|
| `02_CTO.md` | KazakovDmitryS@gmail.com |
| `03_ML.md` | CEO, зона ML |
| `04_BACKEND.md` | krisstyushac@gmail.com |
| `05_ORNITHOLOGIST.md` | olgatorshina7@gmail.com, отдельный чат |
| `06_GIS.md` | karimovad39@gmail.com |
| `07_FIELD.md` | olgatorshina7@gmail.com, отдельный чат |
