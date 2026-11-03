# 0002. Образ MinIO для разработки

- Статус: принято
- Дата: 2026-11-03

## Контекст

Для dev нужно S3-совместимое хранилище. Официальные образы `minio/minio` (Docker Hub) и `quay.io/minio/minio` больше не скачиваются: MinIO перестал публиковать сборки community-версии.

## Решение

Используем `cgr.dev/chainguard/minio:latest` — Chainguard собирает MinIO из исходников (на 2026-11-03 — RELEASE.2026-10-23). В образе есть `mc`: им делаем healthcheck (`mc ready local`) и создаём бакет в одноразовом сервисе `minio-init`.

Код работает с хранилищем только по S3 API (`S3_ENDPOINT_URL`), поэтому привязки к MinIO нет.

## Последствия

- Бесплатный Chainguard отдаёт только тег `latest` — версия может меняться между `make up`. Для dev это приемлемо.
- Прод — Object Storage Yandex Cloud (SPEC.md), MinIO там не используется.
- Альтернативы, если образ пропадёт: `pgsty/minio`, RustFS, SeaweedFS.
