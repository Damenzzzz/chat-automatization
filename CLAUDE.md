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
make test               # pytest api + ml
make lint               # ruff, mypy, eslint, prettier, tsc
make fmt                # автоформат
make down
```

Порты: api 8000, ml 8001, web 3000, postgres **5433**, redis 6379, minio 9000/9001. Занят порт — переопредели `*_PORT` в `.env` или в окружении (`API_PORT=18000 make up`).

## Правила

- **Мультиарендность:** у каждой таблицы есть `tenant_id` и политика RLS. Без исключений.
- **Цена и остаток** берутся только из БД (колонки `products.price`, `products.stock`) — никогда из эмбеддингов, контекста или «из головы» модели. Ответ с ценой, которой нет в каталоге, не отправляется.
- **LLM** вызывается только через модуль `apps/api/app/llm`. Прямые импорты SDK Gemini в другом месте запрещены.
- **Секреты** только из переменных окружения (`app/core/config.py`). Никаких ключей в коде, тестах и коммитах.
- **Деньги:** суммы в тенге — целые числа (`int`, `BIGINT`); себестоимость в USD — `Decimal` (`NUMERIC`). Float для денег не использовать.

## Модели

| Задача | Модель | Где |
| --- | --- | --- |
| Понимание запроса (язык, намерение, слоты) | `gemini-3.1-flash-lite` | Gemini API |
| Ответ по умолчанию | `gemini-3.5-flash-lite` | Gemini API |
| Сложный диалог | `gemini-3.6-flash` | Gemini API |
| Эмбеддинги | Qwen3-Embedding-0.6B | локально, apps/ml |
| Реранкер | Qwen3-Reranker-0.6B | локально, apps/ml |
| Голос → текст | faster-whisper | локально, apps/ml |

Ключ Gemini — ключ Vertex AI: клиент создаётся с `vertexai=True` (`GEMINI_USE_VERTEXAI=true`).

## Процесс

- Каждый шаг заканчивается зелёными `make lint` и `make test` и коммитом.
- Каждый шаг — 5–10 атомарных коммитов; код и его тесты в одном коммите.
- Формат — Conventional Commits (`feat(api): ...`, `fix(web): ...`, `chore: ...`, `docs: ...`, `ci: ...`).
- Не пушить без просьбы.
- Значимые решения — новый файл в `docs/adr/`.
