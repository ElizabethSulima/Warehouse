# Склад с pub/sub

Два асинхронных сервиса в одном репозитории, общаются через Redis pub/sub, хранилище — PostgreSQL.
Все запросы — SQLAlchemy Core (без ORM) поверх asyncpg.

| Сервис | Каталог | Роль |
|---|---|---|
| Сервис 1 | `inventory_api/` (aiohttp) | приём поступлений/расходов, остатки, аналитика, публикация событий |
| Сервис 2 | `analytics_worker/` | подписка на `inventory.receipt` / `inventory.issue`, обновление `stock_agg` |
| Общий код | `common/` | схема таблиц, SQL-запросы, контракт событий, раннер миграций |

```
POST /receipts|/issues ─▶ stock_events (PostgreSQL) ─▶ PUBLISH inventory.receipt|issue ─▶ Redis
                                                                                           │
                                         stock_agg (UPSERT) ◀── analytics_worker ◀─────────┘
```

## Быстрый старт (Docker)

```bash
docker compose up --build
```
Поднимутся Postgres, Redis, одноразовый контейнер миграций, API (`http://localhost:8080`) и воркер.

## Запуск локально

Нужен Python ≥ 3.10, запущенные Postgres и Redis (проще всего: `docker compose up -d postgres redis`).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env

python -m common.migrate        # миграции (migrations/*.sql)
python -m inventory_api         # терминал 1: API на :8080
python -m analytics_worker      # терминал 2: воркер
```

## Миграции

SQL-файлы в `migrations/` применяются по порядку командой `python -m common.migrate`;
применённые записываются в таблицу `schema_migrations`. Новая миграция — новый файл `002_*.sql`.

Таблицы:
- `stock_events` — журнал операций (`event_type` = receipt | issue, `sku`, `warehouse`, `qty > 0`, `created_at`);
- `stock_agg` — агрегат остатков, PK `(warehouse, sku)`.

## API

```bash
curl -X POST localhost:8080/receipts -H 'Content-Type: application/json' \
     -d '{"sku":"A-100","qty":50,"warehouse":"WH-1"}'
curl -X POST localhost:8080/issues   -H 'Content-Type: application/json' \
     -d '{"sku":"A-100","qty":20,"warehouse":"WH-1"}'
curl 'localhost:8080/stock?warehouse=WH-1'
curl 'localhost:8080/stock?warehouse=WH-1&sku=A-100'
curl 'localhost:8080/stock/summary?top_n=5'
```

- `POST /receipts`, `POST /issues` → `201 {"event_id": 1, "published": true}`.
  `422` — невалидное тело, `409` — расход больше остатка.
- `GET /stock?warehouse=…[&sku=…]` → `{"warehouse": "WH-1", "items": [{"sku": "A-100", "qty": 30}]}`.
- `GET /stock/summary?top_n=5` →
```json
{
  "warehouses": [{"warehouse": "WH-1", "total_qty": 30, "sku_count": 1}],
  "top_skus": [{"sku": "A-100", "total_qty": 30}]
}
```

## Что где используется из требований

- **GROUP BY и вложенные запросы** — `common/queries.py`: подзапрос `balances` (GROUP BY по `warehouse, sku`
  над журналом) используется внешними GROUP BY по складу и по SKU для `/stock/summary`; в UPSERT воркера
  остаток считается скалярным подзапросом.
- **Redis pub/sub** — API публикует JSON-событие после коммита транзакции; воркер подписан на оба канала,
  валидирует событие (pydantic) и пропускает невалидные сообщения с предупреждением в лог.
- **Обновление, а не добавление** — `INSERT … ON CONFLICT (warehouse, sku) DO UPDATE`.

## Проектные решения

- Источник истины для `/stock` и `/stock/summary` — журнал `stock_events`; `stock_agg` — материализованный
  агрегат, который ведёт воркер.
- Воркер **пересчитывает** остаток пары из журнала, а не прибавляет дельту, поэтому повторная доставка
  события не искажает данные, а порядок сообщений не важен.
- Конкурентность: `pg_advisory_xact_lock` на пару `(warehouse, sku)` — два параллельных расхода не уведут
  остаток в минус, а параллельные пересчёты не перетрут друг друга.
- В `/stock` без `sku` нулевые позиции скрыты; `sku_count` в summary считает SKU с положительным остатком.
- Известное ограничение pub/sub: доставка «at most once». Если воркер был выключен, события теряются
  (в `stock_events` они остаются). Для надёжной доставки можно перейти на Redis Streams с consumer group
  или добавить outbox-таблицу; пересчёт из журнала уже делает такую замену безопасной.

## Тесты

Тесты работают с реальными Postgres и Redis. БД для тестов — отдельная `warehouse_test`
(создаётся автоматически скриптом `docker/init-test-db.sql` при первом старте контейнера Postgres;
в своём Postgres: `createdb warehouse_test`). Перед каждым тестом таблицы очищаются (TRUNCATE).

```bash
docker compose up -d postgres redis
pytest -v
```

Переменные: `TEST_DATABASE_URL` (по умолчанию `postgresql+asyncpg://postgres:postgres@localhost:5432/warehouse_test`),
`TEST_REDIS_URL` (по умолчанию `redis://localhost:6379/1`). На время тестов остановите свой воркер,
иначе он тоже получит тестовые события (pub/sub в Redis не изолирован по номеру БД).

- `tests/test_api.py` — эндпоинты, валидация, отказ при нехватке остатка, summary;
- `tests/test_worker.py` — обработка сообщения, UPSERT одной строки, идемпотентность, невалидные сообщения;
- `tests/test_e2e.py` — API → Redis → воркер → `stock_agg`.
