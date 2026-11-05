SHELL := /bin/bash
.DEFAULT_GOAL := help

ENV_FILES := --env-file .env.example $(if $(wildcard .env),--env-file .env)
COMPOSE := docker compose -f infra/docker-compose.yml $(ENV_FILES)

API := cd apps/api &&
ML := cd apps/ml &&
WEB := cd apps/web &&

.PHONY: help up down logs ps migrate seed admin eval test lint fmt install api-types

help: ## Список команд
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install: ## Поставить зависимости локально (uv, npm) и pre-commit хуки
	$(API) uv sync
	$(ML) uv sync
	$(WEB) npm ci
	uvx pre-commit install

up: ## Поднять все сервисы и дождаться healthcheck
	$(COMPOSE) up -d --build --wait --renew-anon-volumes

down: ## Остановить сервисы (данные в volumes сохраняются)
	$(COMPOSE) down

logs: ## Логи всех сервисов
	$(COMPOSE) logs -f --tail=100

ps: ## Статус сервисов
	$(COMPOSE) ps

migrate: ## Применить миграции Alembic (нужен make up)
	$(COMPOSE) exec api alembic upgrade head

seed: ## Демо-магазин «Цветы Пион» (нужен make migrate)
	$(COMPOSE) exec api python -m app.seed

admin: ## Админ Satushy: make admin ARGS="--email you@satushy.kz"
	$(COMPOSE) exec api python -m app.cli create-admin $(ARGS)

EVAL_MODELS ?= qwen3 bge-m3

eval: ## Качество поиска по моделям EVAL_MODELS → apps/api/eval/results
	@for m in $(EVAL_MODELS); do \
		ML_EMBEDDER=$$m ML_RERANKER=$$m $(COMPOSE) up -d --wait ml && \
		$(COMPOSE) exec -T api python -m scripts.eval_search --label $$m || exit 1; \
	done
	$(COMPOSE) up -d --wait ml

test: ## Тесты api (нужен make up — postgres) и ml
	$(API) uv run pytest
	$(ML) uv run pytest

api-types: ## Типы клиента из OpenAPI работающего api
	$(WEB) npm run api:types

lint: ## ruff, mypy, eslint, prettier, tsc
	$(API) uv run ruff check . && uv run ruff format --check . && uv run mypy
	$(ML) uv run ruff check . && uv run ruff format --check . && uv run mypy
	$(WEB) npm run lint && npm run format:check && npm run typecheck

fmt: ## Автоформат и автоисправления
	$(API) uv run ruff format . && uv run ruff check --fix .
	$(ML) uv run ruff format . && uv run ruff check --fix .
	$(WEB) npm run format
