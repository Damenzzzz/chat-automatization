# Satushy — памятка для разработки

**Продукт.** SaaS для магазинов Казахстана: AI-консультант знает весь каталог магазина и отвечает покупателям в WhatsApp, Instagram, Telegram и на сайте (ru, kk и их смесь). Магазин сам за день подключает бота через мастер настройки; ответы списываются с предоплаченного баланса. Полная спецификация — [SPEC.md](SPEC.md).

## Карта папок

```
apps/api/        FastAPI: кабинет, вебхуки каналов, ARQ-воркер (app/worker.py)
  app/core/      настройки (pydantic-settings), логирование (structlog)
  app/db/        async-движок SQLAlchemy 2, Base
  app/models/    ORM-модели (импортировать в __init__ для Alembic)
  app/llm/       ЕДИНСТВЕННОЕ место вызова LLM
  migrations/    Alembic (async)
apps/ml/         FastAPI для локальных моделей: эмбеддинги, реранкер, whisper
apps/web/        Next.js (App Router, TS, Tailwind 4, shadcn/ui): лендинг и кабинет
infra/           docker-compose.yml для разработки
docs/adr/        архитектурные решения (ADR)
docs/design-tokens.md
```

## Запуск и проверка

```bash
cp .env.example .env    # затем вписать GEMINI_API_KEY и т. п.
make install            # uv sync, npm ci, pre-commit install
make up                 # все сервисы, ждёт healthcheck
make migrate            # alembic upgrade head внутри контейнера api
make seed               # демо-магазин «Цветы Пион»: 30 товаров и база знаний
make admin ARGS="--email you@satushy.kz"   # админ Satushy
make eval               # качество поиска: Qwen3 против BGE-M3
make test               # pytest api + ml; тесты api пересоздают базу satushy_test в docker-postgres
make lint               # ruff, mypy, eslint, prettier, tsc
make fmt                # автоформат
make down
```

Порты на хосте: api **8100**, ml 8001, web 3000, postgres **5433**, redis 6379, minio 9000/9001. Переопределяются через `*_PORT` в `.env`.

## Правила

- **Мультиарендность:** у каждой таблицы есть `tenant_id` и политика RLS `tenant_isolation` (у `tenants` — по `id`). Без исключений.
- **Роли БД:** приложение ходит под `DATABASE_URL` (роль без BYPASSRLS), миграции — под `DATABASE_OWNER_URL`. Запросы к данным магазина — только внутри `tenant_session(tenant_id)` из `app/db/session.py`. Новая таблица в миграции = RLS-политика + явный GRANT роли приложения.
- **ledger** (и `audit_log`) — только вставка: роли приложения выданы лишь SELECT и INSERT, у ledger UPDATE и DELETE запрещены триггером.
- **Цена и остаток** берутся только из БД (колонки `products.price`, `products.stock`) — никогда из эмбеддингов, контекста или «из головы» модели. Ответ с ценой, которой нет в каталоге, не отправляется.
- **LLM** вызывается только через модуль `apps/api/app/llm`. Прямые импорты SDK Gemini в другом месте запрещены.
- **Секреты** только из переменных окружения (`app/core/config.py`). Никаких ключей в коде, тестах и коммитах.
- **Деньги:** суммы в тенге — целые числа (`int`, `BIGINT`); себестоимость в USD — `Decimal` (`NUMERIC`). Float для денег не использовать.

## Вход и роли

- Вход по коду: `POST /auth/request-code` → `POST /auth/verify` (новый номер/почта + `signup` создаёт магазин и владельца). В dev код пишется в лог api (`auth.code`), почта — через SMTP из env, SMS нет.
- Access JWT (15 мин) и refresh (30 дней, ротация, хранится хешем в Redis) — httpOnly cookie. `POST /auth/refresh`, `POST /auth/logout`.
- В эндпоинтах: `CurrentUser`, `require_role(...)`, `TenantDb` из `app/auth/deps.py`. `TenantDb` уже выставил `app.tenant_id` — отдельно `tenant_session` в роутерах не нужен.
- Поиск пользователя до входа — только через SQL-функцию `auth_find_user` (SECURITY DEFINER), RLS не обходить иначе.
- Админ Satushy живёт во внутреннем магазине `SATUSHY_TENANT_ID` (`app/cli.py`). `POST /admin/impersonate/{tenant_id}` → права владельца клиента; старт, стоп и каждый не-GET запрос пишутся в `audit_log` с `actor_id`.

## LLM

- Только через `app.llm`: `get_llm()` → `LLM.generate(model, messages, tools=None, response_schema=None)` → текст, `tool_calls`, `parsed`, `usage`. Без `GEMINI_API_KEY` `get_llm()` возвращает `None` — код обязан работать и без модели.
- Имена моделей — из настроек (`LLM_MODEL_ROUTER/REPLY/COMPLEX`), не строками в коде. Цены — `app/llm/pricing.py`, стоимость — `cost_usd(model, usage)` (Decimal).
- Ретраи на 429/5xx/таймаут встроены в `GeminiLLM`. В тестах — `app.llm.fake.FakeLLM` со сценарием; фикстура `app` по умолчанию отключает LLM.

## Импорт каталога

`POST /catalog/uploads` (xlsx/csv ≤ 20 МБ) или `/catalog/uploads/gsheet` → файл в S3, задача `pending` → `GET /catalog/uploads/{id}/mapping` (эвристика → LLM → сохранённый маппинг источника) → `POST /catalog/uploads/{id}/confirm` → ARQ `ingest_catalog` → `GET /ingest-jobs/{id}`.
Upsert по `(tenant_id, sku_norm)`, без артикула — по `name_hash`. `embedding_stale = true` только при смене статичного текста (`content_hash`: name, description, category, attributes); цена и остаток эмбеддинг не трогают.

## ML-сервис и эмбеддинги

- `apps/ml`: `POST /embed {texts, kind: query|document}` → нормализованные векторы 1024; `POST /rerank {query, documents}` → оценки 0..1; `GET /health` — статус загрузки и модели. Модели грузятся в фоне при старте, до готовности `/embed` и `/rerank` отвечают 503 (клиент API ретраит).
- Бэкенды через env: `ML_EMBEDDER` / `ML_RERANKER` = `bge-m3` (по умолчанию, [ADR 0003](docs/adr/0003-bge-m3-default.md)) | `qwen3` | `fake` (без моделей, для разработки и CI). Кэш Hugging Face — volume `ml-models` (`HF_HOME=/models`), первый старт качает ~4,5 ГБ.
- На CPU модели грузятся в float32 (`ML_DTYPE=auto`; bf16 на CPU в разы медленнее). BGE-M3 эмбеддер + реранкер занимают ~3,5 ГБ RAM, Qwen3 — ~5,5 ГБ (Docker Desktop ≥ 10 ГБ); без памяти — `ML_EMBEDDER=fake ML_RERANKER=fake`. Смена модели = полная переиндексация (все `embedding_stale = true`).
- Тесты на настоящих моделях: `ML_REAL_MODELS=1` (в CI пропускаются); гонять в отдельном контейнере при остановленном `ml`, иначе не хватит памяти.
- В API: `app.mlclient.get_ml_client()`; батчи по 64, ретраи на 429/5xx/сетевые ошибки.
- `reindex_embeddings(tenant_id)` (ARQ) эмбеддит products и kb_chunks с `embedding_stale` или без вектора и снимает флаг, только если строку не меняли во время расчёта (проверка `updated_at`). Ставится после импорта каталога и `make seed`, плюс cron `reindex_all` раз в 10 минут. Текст товара — `app/catalog/embedding_text.py`: без цены и остатка.

## Поиск

- `app.search`: `search_products(session, query, filters)` → топ-5 товаров с ценой и остатком из БД; `search_kb(session, query)` → топ-3 куска базы знаний. Вызывать внутри `tenant_session` / `TenantDb`.
- Конвейер: три списка по 50 — vector (pgvector cosine, `hnsw.iterative_scan = relaxed_order`), fts (`websearch_to_tsquery` russian + simple, слова через ИЛИ), sku (точно и триграммы по `sku_norm`, только если в запросе есть похожий на артикул токен) → RRF (k = 60) → фильтры → реранкер по топ-30 → топ-5. Точное совпадение артикула всегда первое.
- Фильтры `ProductFilters(price_min, price_max, in_stock, category)` стоят и в SQL кандидатов, и повторно после слияния. `in_stock` пропускает неизвестный остаток (`NULL`), но не `0`.
- ML недоступен → поиск работает без вектора и реранкера (fts + sku, порядок RRF).
- Каждый поиск пишется в `search_log` (`kind`, `lang`, `result_count`, `has_in_stock`, `latency_ms`); отладка — `record=False`. Язык — эвристика `app/search/lang.py`, роутер LLM может передать свой.
- `GET /debug/search?q=&tenant_id=` (только admin) — кандидаты, ранги в каждом списке, RRF, оценки реранкера.
- Качество: `make eval` (Qwen3 и BGE-M3 по очереди, переиндексация демо-магазина) → `apps/api/eval/results/<дата>.md`. Набор — `apps/api/eval/queries.jsonl`, 60 запросов (ru 30, kk 15, смесь 15).

## Бот (LangGraph)

- `app/agent`: граф из SPEC.md — ingest → (transcribe) → guard_in → understand → retrieve | kb | order | handoff | respond → respond ⇄ tools (≤ 3) → guard_out → send | respond (1 повтор) | fallback → meter. Переходы — `graph.py`, узлы — `nodes.py`, запуск — `Agent.run(...)` в `runtime.py` (`get_agent` для FastAPI).
- Чекпоинтер — `AsyncPostgresSaver`, `thread_id = conversation_id`, таблицы в схеме `agent_state` ([ADR 0004](docs/adr/0004-agent-checkpoints-schema.md)). Поля хода (`context`, `usage`, `trace`, `tool_hops`, `retries`) сбрасывает `ingest`.
- `understand` — `LLM_MODEL_ROUTER`, `Understanding` (lang, intent, complexity, slots, search_query); без LLM — эвристика. Инъекции в промпт → `offtopic` без вызова модели.
- `respond` — системный промпт из активного `bot_profiles` (`prompt.py`) стоит первым и не меняется между сообщениями; всё динамическое (язык, найденные товары, база знаний, подсказка повтора) — блок «Данные для ответа» в последнем сообщении покупателя. Модель — `LLM_MODEL_REPLY`, при `complexity = high` или диалоге > 12 сообщений — `LLM_MODEL_COMPLEX`.
- Инструменты (`tools.py`): search_products, get_product, search_kb, create_lead (цены из БД, `leads` + ARQ `notify_manager`), handoff (`conversations.mode = human`). Подписи вызовов Gemini 3 (`thoughtSignature`) хранятся в `AIMessage.additional_kwargs` и возвращаются модели.
- `guard_out` (`guard.py`): каждая сумма в ответе (₸, тг, тыс., к) = цена из context, сумма до 4 таких цен, число из профиля бота, базы знаний или сообщения покупателя; артикулы — только из найденных товаров. Не прошло → удаление ответа и 1 повтор с подсказкой → шаблон «уточню у менеджера» + handoff.
- `meter`: сообщение покупателя пишет `ingest`, ответ бота — `meter` (model, суммы tokens_in/out/cached, cost_usd, latency_ms хода, `trace = {steps, llm_calls}`). Не нашли ни товаров, ни базы знаний или сработал fallback → `unanswered`.
- Песочница: `POST /sandbox/chat {message, session_id}` (тот же граф, `conversations.sandbox = true`, без уведомлений и журнала поиска), `POST /sandbox/autotest {count}` — вопросы по каталогу и базе знаний, прогон, судья `LLM_MODEL_REPLY`.
- Профиль бота: `GET/PUT /bot-profile`, `GET /bot-profile/versions`, `POST /bot-profile/rollback {version?}`. Каждое сохранение и откат — новая версия, активна ровно одна.
- В тестах — `FakeLLM` (сценарий по порядку вызовов) и `tests/agent_helpers.py` (`make_conversation`, `make_agent`).

## Модели

| Задача | Модель | Где |
| --- | --- | --- |
| Понимание запроса (язык, намерение, слоты) | `gemini-3.1-flash-lite` | Gemini API |
| Ответ по умолчанию | `gemini-3.5-flash-lite` | Gemini API |
| Сложный диалог | `gemini-3.6-flash` | Gemini API |
| Эмбеддинги | BGE-M3 (запасной — Qwen3-Embedding-0.6B) | локально, apps/ml |
| Реранкер | bge-reranker-v2-m3 (запасной — Qwen3-Reranker-0.6B) | локально, apps/ml |
| Голос → текст | faster-whisper | локально, apps/ml |

Ключ Gemini — ключ Vertex AI: клиент создаётся с `vertexai=True` (`GEMINI_USE_VERTEXAI=true`).

## Процесс

- Каждый шаг заканчивается зелёными `make lint` и `make test` и коммитом.
- Каждый шаг — 5–10 атомарных коммитов; код и его тесты в одном коммите.
- Сообщение коммита — короткий текст на русском, 5–7 слов, без префиксов `feat:`/`docs:`/`chore:`. Планы коммитов в промптах с такими префиксами — переводить в этот формат.
- **НИКОГДА НЕ КООАВТОРИСЬ С КЛОДОМ:** никаких `Co-Authored-By` и упоминаний AI в коммитах и PR.
- Комментарии в коде — по минимуму.
- Не пушить без просьбы.
- Значимые решения — новый файл в `docs/adr/`.
