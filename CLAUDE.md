# Satushy — памятка для разработки

**Продукт.** SaaS для магазинов Казахстана: AI-консультант знает весь каталог магазина и отвечает покупателям в WhatsApp, Instagram, Telegram и на сайте (ru, kk и их смесь). Магазин сам за день подключает бота через мастер настройки; ответы списываются с предоплаченного баланса. Полная спецификация — [SPEC.md](SPEC.md).

## Карта папок

```
apps/api/        FastAPI: кабинет, вебхуки каналов, ARQ-воркер (app/worker.py)
  app/core/      настройки (pydantic-settings), логирование (structlog)
  app/db/        async-движок SQLAlchemy 2, Base
  app/models/    ORM-модели (импортировать в __init__ для Alembic)
  app/llm/       ЕДИНСТВЕННОЕ место вызова LLM
  app/channels/  шлюз каналов: адаптеры, очередь, склейка
  app/billing/   цены, журнал, счёт PDF, уведомления о балансе
  app/analytics/ периоды, метрики, группировка неотвеченных
  migrations/    Alembic (async)
apps/ml/         FastAPI для локальных моделей: эмбеддинги, реранкер, whisper
apps/web/        Next.js (App Router, TS, Tailwind 4): кабинет магазина
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
make api-types          # типы клиента из OpenAPI работающего api
make fmt                # автоформат
make backup             # дамп базы в backups/ (нужен make up)
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
- `ENV` обязателен (`dev` | `test` | `prod`); при `prod` сервис не стартует с `JWT_SECRET` из `.env.example`. `/docs` в проде выключен, готовность — `GET /ready`. Решения — [ADR 0009](docs/adr/0009-safe-defaults.md).
- Выход отзывает access-токен (`jti` в `auth:revoked:*`), `tenants.status = suspended` → 403 `shop_suspended` и молчащий бот (`PUT /admin/tenants/{id}/status`). Кука `satushy_session` — только признак сессии для `apps/web/src/proxy.ts`. Решения — [ADR 0011](docs/adr/0011-sessions-and-housekeeping.md).
- IP клиента для лимитов — только `client_ip` из `app/core/net.py`, лимиты — `limit` из `app/core/ratelimit.py`. `X-Forwarded-For` напрямую не читать.
- Админ Satushy живёт во внутреннем магазине `SATUSHY_TENANT_ID` (`app/cli.py`). `POST /admin/impersonate/{tenant_id}` → права владельца клиента; старт, стоп и каждый не-GET запрос пишутся в `audit_log` с `actor_id`.

## LLM

- Только через `app.llm`: `get_llm()` → `LLM.generate(model, messages, tools=None, response_schema=None)` → текст, `tool_calls`, `parsed`, `usage`. Без `GEMINI_API_KEY` `get_llm()` возвращает `None` — код обязан работать и без модели.
- Имена моделей — из настроек (`LLM_MODEL_ROUTER/REPLY/COMPLEX`), не строками в коде. Цены — `app/llm/pricing.py`, стоимость — `cost_usd(model, usage)` (Decimal).
- Ретраи на 429/5xx/таймаут встроены в `GeminiLLM`. В тестах — `app.llm.fake.FakeLLM` со сценарием; фикстура `app` по умолчанию отключает LLM.

## Импорт каталога

`POST /catalog/uploads` (xlsx/csv ≤ 20 МБ) или `/catalog/uploads/gsheet` → файл в S3, задача `pending` → `GET /catalog/uploads/{id}/mapping` (эвристика → LLM → сохранённый маппинг источника) → `POST /catalog/uploads/{id}/confirm` → ARQ `ingest_catalog` → `GET /ingest-jobs/{id}`.
Upsert по `(tenant_id, sku_norm)`, без артикула — по `name_hash`. `embedding_stale = true` только при смене статичного текста (`content_hash`: name, description, category, attributes); цена и остаток эмбеддинг не трогают.

## ML-сервис и эмбеддинги

- `apps/ml`: `POST /embed {texts, kind: query|document}` → нормализованные векторы 1024; `POST /rerank {query, documents}` → оценки 0..1; `POST /transcribe` (multipart `file`) → текст, язык; `GET /health` — статус загрузки и модели. Модели грузятся в фоне при старте, до готовности `/embed` и `/rerank` отвечают 503 (клиент API ретраит).
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
- Повтор хода ([ADR 0010](docs/adr/0010-turn-idempotency.md)): сообщение покупателя ищется по `external_id`, `send` ставит на нём `trace.answered`; при повторе `ingest` возвращает `duplicate` (`done` → конец, `sent` → сразу `meter`). Второй ответ и второе списание не появляются.
- Сессия диалога — 6 часов тишины (`app/agent/session.py`): длина диалога для выбора модели считается внутри сессии, слоты в новой сессии сбрасываются.
- `tenants.bot_paused` (кабинет, `PATCH /shop`): сообщение сохраняется, бот молчит, режим диалога не меняется; песочница работает.
- `create_lead` не создаёт заявку на количество больше известного остатка; `guard_out` пропускает «цена × количество», если количество есть в ответе или в сообщении покупателя.
- Черновик ответа менеджеру — `app/agent/draft.py` (`POST /conversations/{id}/draft`): тот же профиль и поиск, ничего не сохраняет и не списывает, `verified` — результат `check_reply`.
- В тестах — `FakeLLM` (сценарий по порядку вызовов) и `tests/agent_helpers.py` (`make_conversation`, `make_agent`).

## Каналы

- `app/channels`: `IncomingMessage` / `OutgoingMessage` (текст, карточки, кнопки), адаптеры с интерфейсом `ChannelAdapter` (`parse`, `send`, `download`, `acknowledge`, `check`), реестр — `registry.py`. Решения — [ADR 0005](docs/adr/0005-channel-gateway.md).
- Путь сообщения: вебхук проверяет подпись → `Gateway.accept` (SETNX `dedup:*` на 24 часа, буфер, задача ARQ `flush_customer` через 1,5 с) → `Processor.flush` (последний `seq`, блокировка диалога, склейка) → граф. В режиме human сообщение сохраняется и уходит `notify_manager`.
- `notify_manager` → `app/channels/staff.py`: Telegram всем активным сотрудникам с привязанным чатом (заявка, передача диалога, сбой хода, ожидающий покупатель — не чаще раза в 10 минут на диалог). После трёх неудач `Processor.give_up` отвечает покупателю шаблоном и переводит диалог менеджеру.
- Cron `release_idle` (раз в 10 минут): диалог у менеджера без сообщений `HUMAN_IDLE_RELEASE_HOURS` часов возвращается боту, пауза `rate_limit` снимается через час (SQL-функция `release_idle_conversations`).
- Cron воркера: `sweep_inbox` (буферы без обработки 90 с), `remind_leads` (заявка `new` старше `LEAD_REMINDER_HOURS`), `housekeeping` (закрытие диалогов через 30 дней тишины, удаление старой песочницы и их чекпоинтов, чистка `search_log`). Межарендные выборки — только SQL-функции SECURITY DEFINER из миграций 0017 и 0019.
- Блокировка диалога 120 с, её продлевает `keep_locked`; не полагаться на то, что ход короче TTL.
- Любое изменение диалога или заявки вне этих мест должно вызвать `poke(tenant_id)` (`app/core/poke.py`), иначе кабинет увидит его только через 5 секунд.
- Узел `gate` показывает покупателю «печатает» (`Outbound.typing`: Telegram и WhatsApp). HTTP-клиенты каналов и ML общие на процесс.
- Текст покупателя не класть в аргументы ARQ и логи. Токены не писать в ошибки: `ChannelHttp` убирает URL, логи httpx выключены (в URL Telegram лежит токен).
- Карточки: только товары, упомянутые в ответе (до 3); цена и фото читаются из БД в узле `send`. Ошибка отправки не роняет ход: `delivered = false` и `error` в trace.
- Подключение (только owner): `POST /channels/telegram {token}` (getMe + setWebhook с `secret_token`), `POST /channels/whatsapp`, `POST /channels/web {domain}` (выдаёт `snippet`), `POST /channels/{id}/check`, `GET /channels`.
- Вебхуки: `/webhooks/telegram/{id}` (заголовок `X-Telegram-Bot-Api-Secret-Token`), `/webhooks/whatsapp/{id}` (GET — `hub.verify_token`, POST — `X-Hub-Signature-256` по `app_secret`).
- Виджет: `POST /widget/{key}/messages`, `GET /widget/{key}/stream` (SSE на Redis Streams), заголовок `X-Widget-Session` с токеном из `POST /widget/{key}/session` (подписан сервером, самодельные отклоняются); CORS только для `channels.domain` и его `www`. Лимиты: 20 в минуту на сессию, 60 на IP, `WIDGET_CHANNEL_MESSAGES_PER_HOUR` на канал. Скрипт — `apps/web/public/widget.js`.
- Голос: узел `transcribe` скачивает аудио через адаптер, шлёт в ML, кладёт расшифровку в `messages.content` и `messages.media.items[]`. Не распознали → `voice_failed`, бот просит написать текстом. В `apps/ml` базовая модель определяет язык, `kk` уходит в `KK_ASR_MODEL`; модель в формате Transformers при старте конвертируется в CTranslate2 (`/models/ct2`). `av<18`: faster-whisper 1.2 несовместим с новее. `ML_ASR=fake` — без моделей.
- Env: `FERNET_KEY` обязателен для ключей каналов (иначе 503 `encryption_not_configured`), `PUBLIC_API_URL` должен быть HTTPS для Telegram (локально — адрес туннеля), `WHATSAPP_GRAPH_VERSION`.
- Instagram — только заглушка адаптера, подключим после App Review.
- В тестах: `tests/channel_helpers.py`, адаптеры через `httpx.MockTransport`, фикстуры вебхуков — `tests/fixtures/channels` (написаны по документации, не сняты с живого трафика).

## Биллинг и лимиты

Правила и причины — [ADR 0006](docs/adr/0006-billing-rules.md).

- Цена ответа: `ceil(cost_usd × k × курс)`, минимум 1 ₸ (`app/billing/pricing.py`, только `Decimal`). Настройки: `GET/PUT /admin/pricing`, `PUT /admin/tenants/{id}/pricing`; без них k = 3 и `PRICING_KZT_PER_USD`.
- Баланс — только сумма `ledger` (`get_balance`). Списание — `charge_reply` в узле `meter`, под блокировкой; не больше остатка, в минус не уходит. Без списания: песочница, шаблон без LLM, недоставленный ответ.
- Узел `gate` (после `guard_in`, в песочнице пропускается): баланс ниже средней цены ответа → `no_balance`; 30 ответов бота покупателю за час (`BOT_REPLIES_PER_HOUR`) → `rate_limit`. Оба случая: шаблон без LLM, `mode = human`, `conversations.paused_reason`. Пополнение возвращает боту только `no_balance`.
- Пополнение: `GET /billing/invoice?amount_kzt=` (PDF, реквизиты `BILLING_SELLER_*`, без них 503) → `POST /admin/tenants/{id}/topup {invoice_no}` или `{amount_kzt, provider}`. Повторная оплата счёта — 409.
- Уведомления: 20%, 5% и 0 от последнего пополнения → `notifications` (`GET /notifications`) и Telegram владельца (ARQ `notify_owner`), привязка — `POST /me/telegram/link`.
- `GET /balance`: баланс, расход и число ответов за 7 дней, прогноз в днях.
- Новый тест с ответом бота на канале требует денег: `make_conversation` и `make_shop` пополняют магазин (`funds=0` — без денег).
- Шрифт счёта — подмножество DejaVu в `app/billing/fonts` (кириллица, казахские буквы, ₸).

## Аналитика

- `GET /analytics/overview`, `dialogs_by_day`, `top_queries`, `unanswered` (`date_from`, `date_to`, по умолчанию 7 дней); дни считаются по `ANALYTICS_TIMEZONE`, песочница исключена.
- `unanswered` группирует вопросы эмбеддингами с порогом `UNANSWERED_GROUP_THRESHOLD` (ML недоступен → точное совпадение текста, `grouped_by = text`).
- `POST /unanswered/{id}/answer {answer, also_resolve}` → кусок `kb_chunks` (`source = unanswered`), ARQ `reindex_embeddings`, вопросы решены.

## Кабинет (apps/web)

Смысл оформления и токены — [docs/design-tokens.md](docs/design-tokens.md). Решения — [ADR 0007](docs/adr/0007-cabinet-api-access.md).

- Страницы: `/` (лендинг с живым чатом демо-бота, `components/landing`), `/login`, `/signup`, `/setup?step=1..5`, `/overview` (экран «Сегодня»: очередь `components/overview/queue.tsx`, деньги и воронка), `/dialogs?id=&filter=`, `/leads`, `/products`, `/bot`, `/channels`, `/balance`, `/settings`. `page.tsx` — серверный (metadata), `view.tsx` — клиентский.
- Оформление: небо `sky` — действие и бот, солнце `sun` — «нужен человек», `ink` — текст и меню; разделы — белые `panel` на `canvas`; заголовки Geologica, текст Golos Text. Белый текст на `sky` не ставить.
- `useSession()` отдаёт `me`/`shop` только после гидратации, иначе серверная и клиентская разметка расходятся.
- Prettier сортирует классы по `globals.css`: новую утилиту коммитить вместе с файлами, которые её используют, или раньше них.
- API только через прокси Next: `/api/*` и `/auth/*` (`next.config.ts`, `API_INTERNAL_URL`; при `output: standalone` адрес зашивается при сборке). `/auth` отдельно: refresh-cookie живёт на этом пути.
- Клиент: `api` из `lib/api/client.ts` (openapi-fetch, при 401 один раз обновляет сессию) и `unwrap` + SWR. Ключ SWR — строка с путём: `InboxStream` по SSE сбрасывает всё, что начинается с `/conversations` и `/leads`.
- Новый код ошибки API — текст в `lib/api/errors.ts`. Схема поменялась — `make api-types` и коммит `schema.d.ts`.
- API кабинета: `GET /conversations`, `/conversations/{id}`, `/conversations/stream` (SSE), `POST /conversations/{id}/takeover|release|reply`, `GET/PATCH /leads`, `GET /products`, `GET/PATCH /shop`. Стоимость модели наружу не отдаём: у сообщения только `steps`, без `llm_calls` и `cost_usd`.
- Диалоги: `GET /conversations?q=` (имя, телефон, текст), в `ConversationDetail` — `customer` (история заявок, заметка `PATCH /conversations/{id}/customer`), ответ менеджера сам переводит диалог в режим human, шаблоны ответов — `shop.reply_templates` (настройки). `GET /analytics/overview` отдаёт `spent_kzt`, `found_dialogs`, `leads_done`.
- Оболочка (`components/shell`): пауза бота, счётчики ожидающих и новых заявок, нижняя панель на телефоне, счётчик в заголовке вкладки, палитра ⌘K (`command-palette.tsx`, открыть из кода — `openPalette()`).
- Типы без запущенного api: `app.openapi()` в JSON → `npx openapi-typescript файл.json -o src/lib/api/schema.d.ts`.
- Ответ менеджера кладётся и в чекпоинт бота (`Agent.remember_manager_reply`), иначе после «Вернуть боту» бот его не знает.
- Примитивы — `components/ui`, свои, на нативных `button`, `label`, `select`, `dialog`. Новый шрифт проверять по таблице символов: `ә ғ қ ң ө ұ ү һ і` и ₸.
- Новые страницы в запущенном `next dev` могут отдавать 404 до перезапуска. Новая зависимость в контейнере — `make up` (пересоздаёт анонимный том `node_modules`).

## Демо-режим

Решения — [ADR 0008](docs/adr/0008-demo-mode.md). `DEMO_ENABLED=true` (так в `.env.example`).

- `POST /demo/login` — вход владельцем «Цветы Пион»; `ensure_demo_shop` досеивает каталог, историю (`app/demo/activity.py`, покупатели `demo:*`, пересоздаётся старше 2 дней) и баланс. `make seed` делает то же.
- `POST /demo/chat {message, session_id}` — публичный чат лендинга, граф песочницы, 12 в минуту и 60 в час на IP, `DEMO_CHAT_DAILY_LIMIT` в сутки на всех, в ответе `cards` с ценой из БД.
- Демо-сессия только читает: не-GET запросы отклоняются с `demo_read_only`, кроме списка `DEMO_WRITABLE` в `app/auth/deps.py` (песочница, перехват, ответ, черновик, статус заявки). Новую изменяющую ручку, нужную в демо, добавлять в этот список.
- `POST /auth/request-code` при демо и `ENV != prod` возвращает `demo_code`, форма входа показывает его и подставляет. `GET /me` → `demo`.

## Модели

| Задача | Модель | Где |
| --- | --- | --- |
| Понимание запроса (язык, намерение, слоты) | `gemini-3.1-flash-lite` | Gemini API |
| Ответ по умолчанию | `gemini-3.5-flash-lite` | Gemini API |
| Сложный диалог | `gemini-3.6-flash` | Gemini API |
| Эмбеддинги | BGE-M3 (запасной — Qwen3-Embedding-0.6B) | локально, apps/ml |
| Реранкер | bge-reranker-v2-m3 (запасной — Qwen3-Reranker-0.6B) | локально, apps/ml |
| Голос → текст | faster-whisper large-v3-turbo, для kk — `KK_ASR_MODEL` | локально, apps/ml |

Ключ Gemini — ключ Vertex AI: клиент создаётся с `vertexai=True` (`GEMINI_USE_VERTEXAI=true`).

## Процесс

- Каждый шаг заканчивается зелёными `make lint` и `make test` и коммитом.
- Каждый шаг — 5–10 атомарных коммитов; код и его тесты в одном коммите.
- Сообщение коммита — короткий текст на русском, 5–7 слов, без префиксов `feat:`/`docs:`/`chore:`. Планы коммитов в промптах с такими префиксами — переводить в этот формат.
- **НИКОГДА НЕ КООАВТОРИСЬ С КЛОДОМ:** никаких `Co-Authored-By` и упоминаний AI в коммитах и PR.
- Комментарии в коде — по минимуму.
- Не пушить без просьбы.
- Значимые решения — новый файл в `docs/adr/`.
