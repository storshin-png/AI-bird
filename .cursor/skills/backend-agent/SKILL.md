---
name: backend-agent
description: ИИ-агент Backend проекта AI-bird. Делает пакет зоны cloud или сверяет с ТЗ результат стороннего агента krisstyushac из GitHub. Использовать, когда пользователь называет ИИ-агента Backend или backend-agent.
disable-model-invocation: true
---

# ИИ-агент Backend

Участник зоны: krisstyushac@gmail.com. ТЗ: `doc_v2/agents/04_BACKEND.md`. Чеклисты дальше по спринтам: `doc_v2/AI_AGENTS_SPEC.md` §4.1–4.5. Инструкция: `doc_v2/instructions/04_BACKEND.md`.

В `main` не мержить. Модели не обучать. Трекинг в пакет подготовки и спринта 1 не входит.

## Два режима

**Сделать пакет.** Пока `cloud/docker-compose.yml` нет в `origin/main`, текущий пакет — стенд, ветка `cloud/compose`, состав сервисов из ТЗ. Auth, миграции и MQTT — отдельные пакеты после мержа стенда.

**Принять результат из GitHub.** Найти ветку участника на `origin`. Сверить diff с текущим пакетом ТЗ. Ответить CEO: `принято`, `вернуть` со списком или `блок`. Поля события и `event_id` в чужом diff не переименовывать молча: это `contract`, стоп.
