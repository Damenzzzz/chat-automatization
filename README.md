# Satushy

AI-консультант для магазинов Казахстана: знает весь каталог и отвечает покупателям в WhatsApp, Instagram, Telegram и на сайте.

- Спецификация MVP — [SPEC.md](SPEC.md)
- Памятка для разработки — [CLAUDE.md](CLAUDE.md)

```bash
cp .env.example .env
make up
```

## Лендинг

Сайт команды — статическая сборка лендинга из `apps/web` без кабинета и API (`LANDING_ONLY=1`); заявки с формы принимает функция из `apps/landing/lambda`.

```bash
make landing-test                                  # тесты сайта и функции заявок
make landing-deploy LEADS_EMAIL=you@example.com    # первый запуск: S3, CloudFront, функция заявок
make landing-deploy                                # обновить сайт
```

Как это устроено и почему — [docs/adr/0012-landing-on-aws.md](docs/adr/0012-landing-on-aws.md).
