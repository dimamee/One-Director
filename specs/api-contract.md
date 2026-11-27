# Контракт API

Версия 0.3 (решения D-17, D-18, D-12, D-9 из `specs/decisions.md`; 0.3 — предложения D-45, D-46 по `flags` и «не вычислено»). Реализует 07-backend (`src/one_director/api/`). Роли и матрица — `docs/access-control.md`; классы полей — `specs/schema.md`.

## Общие правила

- Базовый путь: `/` (версия API в заголовке ответа `X-API-Version: 0`). Только JSON (`application/json; charset=utf-8`), кроме PDF.
- **Аутентификация:** `Authorization: Bearer <JWT>` на всех эндпоинтах, кроме `GET /health` и `POST /auth/token`. Нет токена / токен недействителен → `401`; роль не подходит → `403`.
- **Валидация:** все параметры — pydantic-модели (`extra="forbid"`): неизвестный параметр → `400`. Строки — с ограничением длины, перечисления — белые списки.
- **SQL:** только параметризованные запросы DuckDB (`con.execute(sql, params)`); имена колонок для сортировки берутся из словаря `sort → SQL-фрагмент`, а не из запроса.
- **Пагинация:** `limit` 1–100 (по умолчанию 20), `offset` 0–10 000. Ответ содержит `total` (с ограничением: `total_capped: true`, если > 10 000).
- **Маскирование** (`security/masking.py`) применяется до сериализации; в `DEMO_MODE` — для всех ролей.
- **Rate limiting** (на пользователя и на IP; `429` + `Retry-After`):

  | Группа | Лимит |
  |---|---|
  | `POST /auth/token` | 5/мин на IP; 10 неудач подряд → блокировка аккаунта на 15 мин |
  | `GET /lots`, `GET /lots/{trade_id}`, `GET /firms/{firm_ref}` | 60/мин на пользователя, 120/мин на IP |
  | `GET /graph` | 20/мин на пользователя |
  | `GET /reports/{trade_id}.pdf` | 10/мин на пользователя |
  | `GET /health` | 60/мин на IP |

- **Заголовки безопасности** на всех ответах: `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store` (для данных), `Strict-Transport-Security: max-age=31536000` (только при HTTPS). CORS — только `ALLOWED_ORIGINS`, методы `GET, POST`, без `credentials` для чужих origin.
- **Логи:** access log uvicorn выключен; middleware пишет `request_id`, метод, шаблон маршрута (`/firms/{firm_ref}`, без значения), статус, длительность, `ip_hash`.
- **Идентификатор фирмы в API — `firm_ref`, а не ИНН** (решение D-17). `firm_ref = "F-" + первые 16 hex HMAC-SHA256(PSEUDONYM_SALT, "firm:" + inn)`, шаблон `^F-[0-9a-f]{16}$`. Вычисляется в `security.pseudonymize` (Фаза 1). ИНН никогда не попадает в URL; `firm_ref` одинаков во всех режимах, в том числе в `DEMO_MODE`, поэтому из замаскированной карточки лота можно перейти к карточке фирмы и графу. Класс `firm_ref` — `personal` (псевдоним): не логируется значением, в audit_log пишется как `object_id`.
- **Формат `trade_id`** (решение D-9): по ответам API площадки это целое число (например, `524614`); шаблон `^[0-9]{1,12}$`.
- **Документация OpenAPI** (`/docs`, `/openapi.json`) включена только при `APP_ENV=local`.

### Формат ошибки

Одинаковый для всех ошибок; без стек-трейсов, имён модулей, SQL, путей файлов и эха входных значений.

```json
{"error": {"code": "not_found", "message": "Not found", "request_id": "3f6c1e9a-..."}}
```

| HTTP | `code` | Когда |
|---|---|---|
| 400 | `invalid_request` | параметр не прошёл валидацию (без подробностей о значении; допустимо имя параметра) |
| 401 | `unauthorized` / `invalid_credentials` | нет/просрочен/подделан токен; неверный логин или пароль |
| 403 | `forbidden` | роль не подходит; `unmask` в `DEMO_MODE` |
| 404 | `not_found` | объект не найден (одинаково для «нет» и «нет доступа к существованию», где это важно) |
| 413 | `payload_too_large` | тело запроса > 4 КБ |
| 429 | `rate_limited` | превышен лимит; заголовок `Retry-After` |
| 500 | `internal_error` | любая необработанная ошибка (детали — только в логе по `request_id`) |
| 503 | `unavailable` | хранилище недоступно |

FastAPI-ответ `422` с деталями валидации **переопределяется** на `400 invalid_request`.

---

## `GET /health`

- **Роль:** без аутентификации.
- **Параметры:** нет.
- **Ответ `200`:** `{"status": "ok"}` — без версии, имени хоста, конфигурации.
- **Ошибки:** `503` (`{"status": "unavailable"}`), `429`.
- **audit_log:** нет.

## `POST /auth/token`

- **Роль:** без аутентификации.
- **Тело (JSON, ≤ 4 КБ):** `{"username": str 3–64 символа [A-Za-z0-9._-], "password": str 12–128}`. Form-data не принимается.
- **Ответ `200`:** `{"access_token": "<JWT>", "token_type": "bearer", "expires_in": 1800}`.
- **Ошибки:** `400`, `401 invalid_credentials` (одинаково для неизвестного пользователя, неверного пароля и заблокированной учётки), `413`, `429`.
- **audit_log:** да — `login_success` / `login_failure` (`user_id` или `null`, `ip_hash`); пароль никогда не логируется.

## `GET /lots`

Очередь рисков.

- **Роль:** `viewer`, `analyst`, `supervisor`.
- **Параметры (query):**

  | Параметр | Тип | Ограничения | По умолчанию |
  |---|---|---|---|
  | `limit` | int | 1–100 | 20 |
  | `offset` | int | 0–10 000 | 0 |
  | `sort` | enum | `score_desc`, `score_asc`, `deal_date_desc`, `deal_date_asc`, `start_cost_desc` | `score_desc` |
  | `min_score` | int | 0–100 | 0 |
  | `region` | enum | коды регионов из справочника | — |
  | `category` | enum | коды категорий из справочника | — |
  | `date_from`, `date_to` | date | ISO 8601, `date_from ≤ date_to`, диапазон ≤ 3 лет | — |
  | `flag` | enum | коды признаков (`docs/model-card.md`) | — |

- **Ответ `200`:**

  ```json
  {
    "items": [
      {
        "trade_id": "…", "display_no": "…", "title": "…",
        "category": "construction", "region": "tashkent_city",
        "deal_date": "2026-05-14", "start_cost": "…", "deal_cost": "…", "currency": "UZS",
        "participants_count": 2,
        "risk": {"score": 78, "top_reasons": ["SHARED_FOUNDER", "LOW_DISCOUNT", "FEW_BIDDERS"], "model_version": "…"}
      }
    ],
    "limit": 20, "offset": 0, "total": 1234, "total_capped": false, "risk_available": true
  }
  ```

  Названия участников в очереди не возвращаются. `title` — недоверенный текст (экранируется клиентом).

  **До появления `risk_scores`** (решение D-18): `risk` = `null` у каждого элемента, в ответе есть `"risk_available": false`; `sort=score_desc` и `score_asc` в этом состоянии работают как `deal_date_desc` (без ошибки), `min_score` > 0 → пустой список. Когда скоры есть — `"risk_available": true`.
- **Ошибки:** `400`, `401`, `403`, `429`.
- **audit_log:** нет (только агрегированный счётчик в техническом логе).

## `GET /lots/{trade_id}`

Карточка лота.

- **Роль:** `analyst`, `supervisor`.
- **Путь:** `trade_id` — `^[0-9]{1,12}$` (D-9).
- **Query:** `unmask` bool (по умолчанию `false`; только `supervisor` вне `DEMO_MODE`), `reason` str 10–200 (обязателен при `unmask=true`).
- **Ответ `200`:** поля лота из `lots`; `participants`: `[{"ref": "P1", "firm_ref": "F-…", "inn": "*********" | "…", "name": "ООО «А»" | "ИП ***" | "…", "entity_type", "is_winner", "bid_price", "risk": {...}}]`; `flags`: `[{flag_code, severity, evidence, rule_version}]` (evidence с замаскированными идентификаторами: значения под ключами `*_inn` / `*_inns` маскируются как ИНН участников; ключ `params` — применённые пороги — не отдаётся никогда, *предложение* D-46); `not_computed`: `[{flag_code, reason}]` из `screen_coverage` (*предложение* D-45); `risk`; `brief`: `{"ru": …, "uz": …, "legal_refs": [{id, text_ru, text_uz}], "source": "llm" | "template", "prompt_version", "model"}` или `null`; `disclaimer`: фиксированный текст ru/uz.
- **Ошибки:** `400`, `401`, `403` (в т. ч. `unmask` без прав или в `DEMO_MODE`), `404`, `429`.
- **audit_log:** да — `view_lot`; при `unmask=true` дополнительно `unmask` с `reason`.

## `GET /firms/{firm_ref}`

Карточка фирмы.

- **Роль:** `analyst`, `supervisor`.
- **Путь:** `firm_ref` — `^F-[0-9a-f]{16}$` (D-17). ИНН в URL не используется. Неизвестный `firm_ref` → `404`.
- **Query:** `unmask`, `reason` — как у карточки лота.
- **Ответ `200`:** `{"firm_ref", "inn", "name", "entity_type", "registration_date", "risk": {...}, "flags": [...], "lots": [{"trade_id", "deal_date", "is_winner", "risk_score"}] (≤ 100, новые сначала), "links": {"shared_founders": int, "shared_directors": int, "shared_address": bool, "shared_phone": bool}}` — ИНН/имя по правилам маскирования; хеши и `person_id` целиком не возвращаются (только короткий префикс `P-3f2a`).
- **Ошибки:** `400`, `401`, `403`, `404`, `429`.
- **audit_log:** да — `view_firm`; при `unmask=true` — `unmask` с `reason`.

## `GET /graph`

Подграф связей вокруг лота или фирмы.

- **Роль:** `analyst`, `supervisor`.
- **Query:** ровно один из `trade_id` (шаблон как выше) или `firm_ref` (`^F-[0-9a-f]{16}$`); `depth` int 1–2 (по умолчанию 1); `max_nodes` int 10–300 (по умолчанию 150).
- **Ответ `200`:** `{"nodes": [{"id": "n1", "type": "firm" | "person" | "address" | "lot", "label": str ≤ 80, "risk_score": int | null}], "edges": [{"source": "n1", "target": "n2", "type": "bid" | "won" | "co_bid" | "director" | "founder" | "same_address" | "same_phone", "weight": float, "match_basis": str | null}], "truncated": bool}`. Метки — уже замаскированный **простой текст** (клиент экранирует перед pyvis). Узлы людей — `P-xxxx`, адресов — `A-xxxx`; у узлов-фирм в `id` — `firm_ref`. Ребро `co_bid` — совместное участие двух фирм в торгах (`weight` — число общих лотов, D-12); `match_basis` = `via_intermediary` / `name_hash_only` для слабых совпадений (правило слабых признаков, `CLAUDE.md`), иначе `null`.
- **Ошибки:** `400` (оба или ни одного параметра), `401`, `403`, `404`, `429`.
- **audit_log:** да — `view_graph` (`object_id` = центр).

## `GET /reports/{trade_id}.pdf`

Экспорт справки по лоту.

- **Роль:** `supervisor`.
- **Путь:** `trade_id` — `^[0-9]{1,12}$`; строка из пути **никогда** не используется как путь к файлу.
- **Query:** `lang` enum `ru` / `uz` / `both` (по умолчанию `both`).
- **Ответ `200`:** `application/pdf`, PDF строится в памяти; `Content-Disposition: attachment; filename="one-director-<trade_id>-<yyyymmdd>.pdf"` (имя собирает сервер, символы `[0-9A-Za-z_.-]`); `Cache-Control: no-store`. В PDF: дисклеймер на каждой странице, исходные цифры и evidence, версия модели и промпта, ID документа и SHA-256 содержимого в колонтитуле, без внешних ресурсов (встроенные шрифты). Маскирование — как в карточке; в `DEMO_MODE` — всё замаскировано. Лимит размера — 5 МБ.
- **Ошибки:** `400`, `401`, `403`, `404`, `429`, `500`.
- **audit_log:** да — `export_pdf` (`object_id` = `trade_id`, `lang`, SHA-256 PDF).

---

## Чего в API нет намеренно

- Эндпоинтов изменения данных (кроме логина) — данные меняет только пайплайн.
- HTTP-управления пользователями — только CLI администратора.
- Эндпоинта генерации справки LLM по запросу пользователя — перегенерация через отдельную команду `analyst`+ (Фаза 2, с аудитом `regenerate_brief`).
- Массовой выгрузки (CSV/все фирмы).
