# Формат сообщений MQTT от датчика

Статус: **черновик для согласования с CTO**. До этого документа формат пакетов нигде не был записан: в спецификациях были только темы (`AI_AGENTS_SPEC.md` §4.3) и списки полей. Имена полей взяты без переименования из `MVP_SPEC.md` §2.1, `USERFLOW.md` §5.3 и `ARCHITECTURE.md` §3. После согласования документ переносится в `contracts/` отдельным запросом с пометкой `contract`.

## Общее

- Брокер — MQTT 3.1.1, QoS 1.
- Тело — JSON-объект в UTF-8, не больше 16 КБ.
- `timestamp_utc` — ISO 8601 с часовым поясом, например `2026-10-25T03:15:27Z`. Время без пояса не принимается.
- Время не должно опережать часы сервера больше чем на 5 минут. Время раньше 2025 года считается невыставленными часами (`clock_not_set`).
- `device_id` в теле необязателен. Если он есть, он должен совпадать с `device_id` в теме.
- `device_id` — латиница, цифры, `.`, `_`, `-`, до 64 символов, первый символ — буква или цифра.
- Датчик должен быть заведён в `devices` (`POST /api/v1/devices`). Пакеты незаведённого или списанного (`retired`) датчика отклоняются.
- Незнакомые поля не отклоняют пакет, а попадают в лог как `unknown_fields`.

## `birdnet/{device_id}/telemetry`

Короткая телеметрия, `MVP_SPEC.md` §2.1. Пишется в `telemetry`.

| Поле | Тип | Обязательно | Пределы |
|---|---|---|---|
| `timestamp_utc` | строка | да | см. выше |
| `device_id` | строка | нет | = тема |
| `battery_v` | число | нет | 0…10 |
| `temperature_c` | число | нет | −80…100 |
| `bird_flag` | bool | нет | |
| `bird_probability` | число | нет | 0…1 |
| `azimuth_geo_deg` | число | нет | 0 ≤ x < 360 |
| `azimuth_confidence` | число | нет | 0…1 |
| `track_id` | строка | нет | до 64 |
| `quality_flag` | строка | нет | до 32 |
| `event_id` | UUID | нет | связь с событием |

```json
{
  "device_id": "sensor-001",
  "timestamp_utc": "2026-08-06T03:15:27Z",
  "battery_v": 3.71,
  "temperature_c": 14.2,
  "bird_flag": true,
  "bird_probability": 0.93,
  "azimuth_geo_deg": 152.0,
  "azimuth_confidence": 0.78,
  "track_id": "trk-000012",
  "quality_flag": "good"
}
```

Повтор пакета с теми же `device_id` и `timestamp_utc` не создаёт второй строки.

## `birdnet/{device_id}/event`

Событие детекции, `USERFLOW.md` §5.3, и направление, `ARCHITECTURE.md` §3. Пишется в `events` со статусом `received`. Если есть `azimuth_geo_deg`, рядом пишется пеленг в `bearings` с `source = 'edge'`.

| Поле | Тип | Обязательно | Пределы |
|---|---|---|---|
| `event_id` | UUID v4 | да | создаётся на устройстве |
| `timestamp_utc` | строка | да | |
| `bird_flag` | bool | нет | |
| `bird_probability` | число | нет | 0…1 |
| `snr_db` | число | нет | −100…200 |
| `channel_levels` | объект | нет | ключи только `N`, `E`, `S`, `W` |
| `quality_flag` | строка | нет | до 32 |
| `track_id` | строка | нет | до 64 |
| `azimuth_device_deg` | число | нет | 0 ≤ x < 360 |
| `azimuth_geo_deg` | число | нет | 0 ≤ x < 360 |
| `sector` | строка | нет | `N`, `NE`, `E`, `SE`, `S`, `SW`, `W`, `NW` |
| `azimuth_confidence` | число | нет | 0…1 |
| `bearing_quality` | строка | нет | `good`, `medium`, `poor`, `ambiguous` |

```json
{
  "event_id": "6f1c2a3e-1b2c-4d5e-8f90-123456789abc",
  "timestamp_utc": "2026-08-06T03:15:27Z",
  "bird_flag": true,
  "bird_probability": 0.93,
  "snr_db": 14.2,
  "channel_levels": {"N": -31, "E": -28, "S": -35, "W": -40},
  "azimuth_device_deg": 62.5,
  "azimuth_geo_deg": 152.5,
  "sector": "SE",
  "azimuth_confidence": 0.78,
  "bearing_quality": "good"
}
```

Второе событие с тем же `event_id` не пишется, даже если время в нём другое.

## `birdnet/{device_id}/heartbeat`

Признак жизни. Пишется в `telemetry` строкой без полей птицы. Если пришла новая `firmware_version`, она записывается в `devices`.

| Поле | Тип | Обязательно |
|---|---|---|
| `timestamp_utc` | строка | да |
| `device_id` | строка | нет |
| `battery_v` | число | нет |
| `temperature_c` | число | нет |
| `firmware_version` | строка | нет |

## Причины отказа в логе

| `reason` | Что не так |
|---|---|
| `bad_topic` | Тема не `birdnet/{device_id}/telemetry|event|heartbeat` |
| `bad_device_id` | Недопустимые символы в `device_id` |
| `bad_json` | Тело не JSON-объект |
| `payload_too_large` | Больше 16 КБ |
| `missing_<поле>` | Нет обязательного поля |
| `invalid_<поле>` | Поле вне пределов или не того типа |
| `bad_event_id` | `event_id` нет или это не UUID v4 |
| `device_id_mismatch` | `device_id` в теле не совпадает с темой |
| `timestamp_in_future` | Время опережает сервер больше чем на 5 минут |
| `clock_not_set` | Время раньше 2025 года |
| `unknown_device` | Датчика нет в `devices` |
| `device_retired` | Датчик списан |
| `db_error` | Ошибка БД; приём продолжается |

## Вопросы к CTO

1. `USERFLOW.md` §5.7 в примере пакета пишет `"quality": "good"`, а `MVP_SPEC.md` §2.1 и `contracts/README.md` называют поле `quality_flag`. Принимается `quality_flag`. Поле `quality` сейчас попадёт в лог как незнакомое и не запишется.
2. `USERFLOW.md` §5.4 в примере пишет `"event_id": "evt-000123"`, а `AI_AGENTS_SPEC.md` §7.2 требует UUID v4. Принимается только UUID v4.
3. LoRaWAN-пакет короткий. Если телеметрия идёт через сетевой сервер LoRaWAN (ChirpStack, TTN), он публикует в MQTT свой конверт, а не этот JSON. Нужен ли конвертер на стороне облака или прошивка шлёт JSON — решить до спринта 2.
