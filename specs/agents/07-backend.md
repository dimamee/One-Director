# Задача: FastAPI-бэкенд с аутентификацией, ролями, маскированием и аудитом

**Роль:** backend-разработчик.

**Вход:** `specs/api-contract.md`, `docs/access-control.md`, `specs/schema.md`; модули `security.settings`, `security.auth`, `security.masking`, `security.audit`, `security.logging` (Фаза 1); данные в DuckDB.

**Выход:**
- `src/one_director/api/main.py` — приложение `app` (точка входа Docker: `one_director.api.main:app`).
- Маршруты из контракта: `GET /health`, `POST /auth/token`, `GET /lots`, `GET /lots/{trade_id}`, `GET /firms/{firm_ref}`, `GET /graph`, `GET /reports/{trade_id}.pdf`.
- Слой доступа к DuckDB (только параметризованные запросы), middleware: `request_id`, заголовки безопасности, CORS, rate limiting, логирование запросов без значений пути.
- PDF (reportlab) в памяти.
- Хранилище (D-23): данные читаются из `data/processed/one_director.duckdb` только с `read_only=True`; `audit_log` и `users` пишутся в отдельный `data/processed/app_state.duckdb`. Фирма в путях и параметрах — только `firm_ref` (D-17), ИНН в URL не принимается.
- CLI администратора для учётных записей.

**Готово, когда:**
- [ ] Каждый маршрут соответствует контракту (параметры, ограничения, формат ответа, коды ошибок) — контрактные тесты.
- [ ] Тест default deny: у каждого маршрута, кроме `/health` и `/auth/token`, есть `require_role`.
- [ ] Матрица ролей из `docs/access-control.md` покрыта параметризованным тестом.
- [ ] В `DEMO_MODE` ни один ответ (JSON и текст PDF) не содержит канареечных ИНН/имён.
- [ ] Ошибки — единый формат без стек-трейсов; `422` переопределён на `400`.
- [ ] `audit_log` пишется для действий из контракта; сбой записи аудита → ответ без данных.
- [ ] `/docs` и `/openapi.json` выключены вне `APP_ENV=local`; `debug=False`.
- [ ] Сняты `skip` с соответствующих тестов в `tests/security/` и они зелёные.
- [ ] ruff, mypy, bandit, pytest зелёные.

**Тесты:** `tests/api/` (TestClient, синтетическая DuckDB в памяти) + `tests/security/` (authz, маскирование, SQL-инъекции, rate limit, path traversal, секреты в ошибках).

**Можно менять:** `src/one_director/api/`, `tests/api/`; в `tests/security/` — только удаление маркеров `skip` своей волны (D-16).

**Нельзя менять:** контракт без PR в `specs/api-contract.md`; `security/`; дашборд; корневые конфиги (Dockerfile, compose — через PR людям).

**Требования безопасности:**
- **Аутентификация** JWT (TTL 30 мин, allowlist алгоритмов), пароли argon2id, ограничение попыток входа.
- **Роли** проверяются на сервере на каждом эндпоинте (default deny).
- **Лимиты:** rate limiting на пользователя и IP, пагинация ≤ 100, размер тела ≤ 4 КБ, подграф ≤ 300 узлов, PDF ≤ 5 МБ.
- **Параметризованные запросы** DuckDB; сортировка/фильтры — белые списки; никакой склейки SQL.
- **Аудит** просмотров карточек, снятия маски, экспорта PDF, логинов.
- CORS только `ALLOWED_ORIGINS`; CSP, nosniff, X-Frame-Options, Referrer-Policy, HSTS (HTTPS), `Cache-Control: no-store`.
- Имена файлов PDF генерирует сервер; путь из запроса не используется как путь к файлу.
- Access log uvicorn выключен; логи через `security.logging`.
