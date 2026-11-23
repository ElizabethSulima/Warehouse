"""Сервис 1: приём операций, остатки, аналитика, публикация событий."""

from __future__ import annotations

import json
import logging

import redis.asyncio as aioredis
from aiohttp import web
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import create_async_engine

from common import config, queries
from common.events import (
    CHANNEL_BY_TYPE,
    EventType,
    InventoryEvent,
    OperationIn,
)

logger = logging.getLogger("inventory_api")
routes = web.RouteTableDef()


def _error(exc_cls, message: str, details=None):
    body = {"error": message}
    if details is not None:
        body["details"] = details
    return exc_cls(
        text=json.dumps(body, ensure_ascii=False),
        content_type="application/json",
    )


async def _read_operation(request: web.Request) -> OperationIn:
    try:
        data = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise _error(web.HTTPBadRequest, "invalid JSON")
    try:
        return OperationIn.model_validate(data)
    except ValidationError as e:
        details = json.loads(
            e.json(
                include_url=False, include_context=False, include_input=False
            )
        )
        raise _error(web.HTTPUnprocessableEntity, "validation error", details)


async def _handle_operation(
    request: web.Request, event_type: EventType
) -> web.Response:
    op = await _read_operation(request)
    engine = request.app["engine"]

    async with engine.begin() as conn:
        await queries.lock_pair(conn, op.warehouse, op.sku)
        if event_type == "issue":
            balance = await queries.get_balance(conn, op.warehouse, op.sku)
            if balance < op.qty:
                raise _error(
                    web.HTTPConflict,
                    "insufficient stock",
                    {"available": balance, "requested": op.qty},
                )
        row = await queries.insert_event(
            conn, event_type, op.warehouse, op.sku, op.qty
        )

    event = InventoryEvent(
        event_id=row.id,
        event_type=event_type,
        sku=op.sku,
        warehouse=op.warehouse,
        qty=op.qty,
        occurred_at=row.created_at,
    )
    published = True
    try:
        await request.app["redis"].publish(
            CHANNEL_BY_TYPE[event_type], event.model_dump_json()
        )
    except Exception:
        published = False
        logger.exception("failed to publish event %s", row.id)

    return web.json_response(
        {"event_id": row.id, "published": published}, status=201
    )


@routes.post("/receipts")
async def post_receipt(request: web.Request) -> web.Response:
    return await _handle_operation(request, "receipt")


@routes.post("/issues")
async def post_issue(request: web.Request) -> web.Response:
    return await _handle_operation(request, "issue")


@routes.get("/stock")
async def get_stock(request: web.Request) -> web.Response:
    warehouse = request.query.get("warehouse", "").strip()
    if not warehouse:
        raise _error(
            web.HTTPBadRequest, "query parameter 'warehouse' is required"
        )
    sku = request.query.get("sku", "").strip() or None
    async with request.app["engine"].connect() as conn:
        items = await queries.get_stock(conn, warehouse, sku)
    return web.json_response({"warehouse": warehouse, "items": items})


@routes.get("/stock/summary")
async def get_stock_summary(request: web.Request) -> web.Response:
    raw = request.query.get("top_n", "5")
    try:
        top_n = int(raw)
        if not 1 <= top_n <= 1000:
            raise ValueError
    except ValueError:
        raise _error(
            web.HTTPBadRequest, "'top_n' must be an integer between 1 and 1000"
        )
    async with request.app["engine"].connect() as conn:
        data = await queries.get_summary(conn, top_n)
    return web.json_response(data)


@routes.get("/health")
async def health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def _resources(app: web.Application):
    engine = create_async_engine(
        app["database_url"], pool_size=10, pool_pre_ping=True
    )
    redis = aioredis.from_url(app["redis_url"], decode_responses=True)
    app["engine"], app["redis"] = engine, redis
    yield
    await redis.aclose()
    await engine.dispose()


def create_app(
    database_url: str | None = None, redis_url: str | None = None
) -> web.Application:
    app = web.Application()
    app["database_url"] = database_url or config.DATABASE_URL
    app["redis_url"] = redis_url or config.REDIS_URL
    app.add_routes(routes)
    app.cleanup_ctx.append(_resources)
    return app
