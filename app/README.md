# app/ — дашборд инспектора (Streamlit)

Владелец: агент 08-frontend (`specs/agents/08-frontend.md`). В Фазе 0 — пусто.

Правила:
- Дашборд получает данные **только через API** (`API_BASE_URL`); прямой доступ к DuckDB, `data/` и секретам запрещён — так роли, маскирование и аудит работают в одном месте.
- Все строки из данных (названия фирм, лотов, заказчиков) экранируются: они могут содержать HTML/JS.
- Небезопасный HTML-рендеринг Streamlit (`unsafe_allow_html`) с данными запрещён — проверяет хук pre-commit `no-unsafe-allow-html`.
- Подписи узлов pyvis экранируются до передачи в pyvis.
- Без внешних CDN, трекеров и аналитики; `browser.gatherUsageStats=false`.
- В `DEMO_MODE` — баннер «Демо-режим: данные замаскированы».
- Тексты — по `docs/glossary-uz-ru.md`, формулировки «признаки возможного нарушения».

Точка входа (будет): `app/main.py`, запуск — `docker compose up dashboard` или `streamlit run app/main.py`.
