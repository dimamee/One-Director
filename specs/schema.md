# Схема данных

Версия 0.1 (Фаза 0). Хранилище: Parquet в `data/processed/` + DuckDB (`data/processed/one_director.duckdb`). Pydantic-модели таблиц реализует 01-data в `src/one_director/data/schema.py`; изменение схемы — сначала PR в этот файл, потом код.

## Классы чувствительности

| Класс | Значение |
|---|---|
| `public` | открыто опубликовано площадкой/госорганом и не относится к физлицу |
| `personal` | персональные данные (физлица, ИП), **включая псевдонимы и хеши** |
| `sensitive` | может навредить при утечке (флаги, скоры, справки, аудит, пороги) |
| `secret` | ключи, хеши паролей |

Запись «`public` / `personal`» означает: `public` для юрлица, `personal` для ИП/физлица и для неизвестного типа (маскируется как ИП).

## Общие правила

- Все времена — `TIMESTAMPTZ` в UTC; даты — `DATE`.
- Денежные суммы — `DECIMAL(20, 2)` в валюте `currency` (не float).
- ИНН (STIR) — `VARCHAR(9)`, только цифры, валидируется регуляркой `^[0-9]{9}$`. Формат идентификаторов площадки (`trade_id`) **сверить с фикстурами** (открытый вопрос); до этого — `VARCHAR(32)`, `^[0-9A-Za-z_-]{1,32}$`.
- Текстовые поля из источника (`title`, `*_name`) — **недоверенный ввод**: хранятся как есть, экранируются при выводе, не передаются в LLM как инструкции.
- Каждая таблица, наполняемая из источника, имеет технические поля `collected_at TIMESTAMPTZ` и `source` (`etender` / `registry`) — в таблицах ниже не повторяются.
- Источник `computed` — значение вычисляется нашим кодом.

## `lots` — лоты и сделки

| Поле | Тип | Nullable | Источник | Класс | Описание |
|---|---|---|---|---|---|
| `trade_id` | VARCHAR(32) | нет (PK) | etender | public | идентификатор торгов на площадке |
| `display_no` | VARCHAR(64) | да | etender | public | номер лота для отображения |
| `title` | VARCHAR(1000) | нет | etender | public (недоверенный текст) | название/предмет лота |
| `category` | VARCHAR(64) | да | etender → нормализация | public | код категории (белый список) |
| `customer_inn` | VARCHAR(9) | нет | etender | public | ИНН заказчика (госорган/госпредприятие) |
| `customer_name` | VARCHAR(500) | да | etender | public (недоверенный текст) | название заказчика |
| `start_cost` | DECIMAL(20,2) | нет | etender | public | стартовая цена |
| `deal_cost` | DECIMAL(20,2) | да | etender | public | цена сделки/договора (нет у несостоявшихся) |
| `currency` | VARCHAR(3) | нет | etender | public | ISO 4217, обычно `UZS` |
| `deal_date` | DATE | да | etender | public | дата сделки |
| `region` | VARCHAR(64) | да | etender → нормализация | public | код региона (белый список) |
| `participants_count` | SMALLINT | да | etender | public | число участников по данным площадки; **не пересчитывается из `bids`** — расхождение с числом записей в `bids` нужно видеть (R2, `specs/agents/04-graph.md`) |
| `status` | VARCHAR(32) | нет | etender → нормализация | public | `completed` / `cancelled` / `failed` / `other` |
| `source_url` | VARCHAR(500) | нет | computed | public | ссылка на страницу лота (документы не скачиваются) |

## `bids` — участники и заявки

| Поле | Тип | Nullable | Источник | Класс | Описание |
|---|---|---|---|---|---|
| `trade_id` | VARCHAR(32) | нет (FK `lots`) | etender | public | |
| `participant_inn` | VARCHAR(9) | нет | etender | public / **personal** | ИНН участника |
| `participant_name` | VARCHAR(500) | да | etender | public / **personal** (недоверенный текст) | название/имя участника |
| `is_winner` | BOOLEAN | нет | etender | public | победитель |
| `bid_price` | DECIMAL(20,2) | **да** | etender | public | цена заявки; может быть недоступна |
| `submitted_at` | TIMESTAMPTZ | **да** | etender | public | время подачи; может быть недоступно |
| `participant_status` | VARCHAR(32) *(тип уточнить)* | **да** | etender → нормализация | public | *предложение*: статус записи `GetProposalUsers` (заявка / отзыв / допуск / отклонение — значения пока неизвестны). **Ждём ответа UZEX/RTAM, что означают лишние записи в `GetProposalUsers`** (R2). До ответа — `null`; граф соучастия строится по правилу из `specs/agents/04-graph.md` |

PK: (`trade_id`, `participant_inn`). Открытый вопрос (R2): если лишние записи `GetProposalUsers` — повторные записи того же ИНН (например, отзыв и новая подача), этот PK не подойдёт; решение — после ответа UZEX/RTAM, отдельным PR.

## `firms` — фирмы (только участники флагнутых лотов)

| Поле | Тип | Nullable | Источник | Класс | Описание |
|---|---|---|---|---|---|
| `inn` | VARCHAR(9) | нет (PK) | etender / registry | public / **personal** | |
| `name` | VARCHAR(500) | да | registry / etender | public / **personal** | |
| `entity_type` | VARCHAR(16) | нет | registry | public | `legal` / `sole_proprietor` / `foreign` / `unknown`; `unknown` маскируется как ИП |
| `registration_date` | DATE | да | registry | public / personal | дата регистрации |
| `address_hash` | VARCHAR(64) | да | registry → HMAC `addr:` | **personal** (псевдоним) | хеш нормализованного юр. адреса |
| `phone_hash` | VARCHAR(64) | да | registry → HMAC `phone:` | **personal** (псевдоним) | хеш телефона в E.164 |
| `director_person_id` | VARCHAR(64) | да | registry → HMAC `person:` | **personal** (псевдоним) | директор |
| `founder_person_ids` | VARCHAR(64)[] | да | registry → HMAC `person:` | **personal** (псевдоним) | учредители-физлица |
| `founder_firm_inns` | VARCHAR(9)[] | да | registry | public / personal | учредители-юрлица (*предложение*: нужно для общего учредителя-юрлица) |
| `registry_checked_at` | TIMESTAMPTZ | нет | computed | public | когда запрашивался реестр |

## `persons` — псевдонимы людей (связи «человек — фирма — роль»)

ФИО **не хранится** ни в каком виде, кроме HMAC.

| Поле | Тип | Nullable | Источник | Класс | Описание |
|---|---|---|---|---|---|
| `person_id` | VARCHAR(64) | нет | registry → HMAC | **personal** (псевдоним) | `HMAC-SHA256(PSEUDONYM_SALT, "person:" + norm(ФИО))`, hex |
| `role` | VARCHAR(16) | нет | registry | personal | `director` / `founder` |
| `firm_inn` | VARCHAR(9) | нет | registry | public / personal | *дополнение к ТЗ*: фирма, в которой человек занимает роль |
| `observed_at` | TIMESTAMPTZ | нет | computed | public | *дополнение к ТЗ*: когда связь зафиксирована |

PK: (`person_id`, `firm_inn`, `role`). Поля `firms.director_person_id` / `founder_person_ids` — денормализованная копия для удобства признаков.

## `flags` — признаки

| Поле | Тип | Nullable | Источник | Класс | Описание |
|---|---|---|---|---|---|
| `flag_id` | VARCHAR(36) | нет (PK) | computed | sensitive | UUID |
| `object_type` | VARCHAR(8) | нет | computed | sensitive | `lot` / `firm` / `pair` |
| `object_id` | VARCHAR(64) | нет | computed | sensitive / personal | `trade_id`, `inn` или `inn1:inn2` (для пары, отсортировано) |
| `flag_code` | VARCHAR(32) | нет | computed | sensitive | код из `docs/model-card.md`, раздел 3 |
| `severity` | VARCHAR(8) | нет | computed | sensitive | `low` / `medium` / `high` |
| `evidence` | JSON | нет | computed | sensitive | воспроизводимые факты: ID лотов, значения, `rule_version`, `match_basis`; без ФИО |
| `rule_version` | VARCHAR(32) | нет | computed | sensitive | версия правила |
| `created_at` | TIMESTAMPTZ | нет | computed | sensitive | |

Значения `evidence.match_basis` для слабых совпадений: `name_hash_only` — совпадение только по ФИО (`docs/model-card.md`); `via_intermediary` — общий контакт через узел-посредник (R1, `specs/agents/04-graph.md`). Детектор посредников новых колонок не требует.

## `risk_scores` — риск-скоры

| Поле | Тип | Nullable | Источник | Класс | Описание |
|---|---|---|---|---|---|
| `object_type` | VARCHAR(8) | нет | computed | sensitive | `lot` / `firm` |
| `object_id` | VARCHAR(64) | нет | computed | sensitive / personal | `trade_id` или `inn` |
| `score` | SMALLINT | нет | computed | sensitive | 0–100 (CHECK) |
| `top_reasons` | JSON | нет | computed | sensitive | ровно 3 элемента `{code, contribution, facts_ref}` |
| `model_version` | VARCHAR(64) | нет | computed | sensitive | версия кода + хеш конфигурации + хеш обучающего среза |
| `computed_at` | TIMESTAMPTZ | нет | computed | sensitive | |

PK: (`object_type`, `object_id`, `model_version`). Старые версии не перезаписываются.

## `audit_log` — журнал доступа (только добавление)

| Поле | Тип | Nullable | Источник | Класс | Описание |
|---|---|---|---|---|---|
| `ts` | TIMESTAMPTZ | нет | computed | sensitive | время события (UTC) |
| `user_id` | VARCHAR(64) | да | API | personal | `null` для неуспешного логина неизвестного пользователя |
| `role` | VARCHAR(16) | да | API | sensitive | роль на момент действия |
| `action` | VARCHAR(32) | нет | API | sensitive | `login_success`, `login_failure`, `view_lot`, `view_firm`, `view_graph`, `unmask`, `export_pdf`, `regenerate_brief`, `user_change` |
| `object_type` | VARCHAR(8) | да | API | sensitive | `lot` / `firm` / `graph` / `user` |
| `object_id` | VARCHAR(64) | да | API | sensitive / personal | ID объекта (может быть ИНН ИП) |
| `ip_hash` | VARCHAR(64) | нет | API → HMAC `ip:` | personal (псевдоним) | |
| `request_id` | VARCHAR(36) | нет | API | sensitive | *дополнение*: связь с техническим логом |
| `reason` | VARCHAR(200) | да | API | sensitive | *дополнение*: обязательно для `unmask` |
| `prev_hash` | VARCHAR(64) | нет | computed | sensitive | *дополнение*: хеш предыдущей записи |
| `record_hash` | VARCHAR(64) | нет | computed | sensitive | *дополнение*: `SHA-256(prev_hash ‖ canonical_json(запись))` |

## Дополнительные таблицы (предложение, утвердить людям)

### `briefs` — кэш справок LLM

| Поле | Тип | Nullable | Источник | Класс | Описание |
|---|---|---|---|---|---|
| `trade_id` | VARCHAR(32) | нет | computed | sensitive | |
| `facts_hash` | VARCHAR(64) | нет | computed | sensitive | SHA-256 канонического JSON фактов |
| `prompt_version` | VARCHAR(16) | нет | computed | sensitive | |
| `model` | VARCHAR(64) | нет | LLM | sensitive | модель, фактически ответившая (или `template`) |
| `content` | JSON | нет | LLM / шаблон | sensitive | `{ru, uz, legal_ref_ids}` с плейсхолдерами |
| `validation` | VARCHAR(16) | нет | computed | sensitive | `passed` / `template_fallback` |
| `created_at` | TIMESTAMPTZ | нет | computed | sensitive | |

### `users` — учётные записи

| Поле | Тип | Nullable | Источник | Класс | Описание |
|---|---|---|---|---|---|
| `user_id` | VARCHAR(36) | нет (PK) | admin | personal | UUID |
| `username` | VARCHAR(64) | нет (UNIQUE) | admin | personal | |
| `password_hash` | VARCHAR(200) | нет | admin → argon2id | **secret** | |
| `role` | VARCHAR(16) | нет | admin | sensitive | `viewer` / `analyst` / `supervisor` / `admin` |
| `active` | BOOLEAN | нет | admin | sensitive | |
| `failed_logins` | SMALLINT | нет | API | sensitive | для блокировки |
| `locked_until` | TIMESTAMPTZ | да | API | sensitive | |
| `created_at` | TIMESTAMPTZ | нет | admin | sensitive | |

## Чего в схеме нет намеренно

ФИО людей, паспортные данные, ПИНФЛ, личные телефоны и домашние адреса физлиц, e-mail, документы и договоры, IP в открытом виде, значения секретов.

**Открытый вопрос: e-mail и IP подачи заявок.** Сейчас не собираются. Если комитет или RTAM официально даст эти поля, они добавляются отдельным PR только как HMAC-хеши и сразу как слабый признак (R1, правило в `CLAUDE.md`, `specs/agents/04-graph.md`).
