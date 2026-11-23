"""Сервис 2: подписка на Redis pub/sub и обновление stock_agg."""

from __future__ import annotations

import asyncio
import logging

import redis.asyncio as aioredis
from pydantic import ValidationError
from redis import exceptions as redis_exc
from sqlalchemy.ext.asyncio import AsyncEngine

from common import queries
from common.events import CHANNELS, InventoryEvent

logger = logging.getLogger("analytics_worker")


async def process_message(engine: AsyncEngine, raw: str | bytes) -> bool:
    """Валидирует сообщение и обновляет агрегат. False — сообщение невалидно"""
    try:
        event = InventoryEvent.model_validate_json(raw)
    except ValidationError as e:
        logger.warning(
            "invalid event skipped: %s | payload=%r",
            e.errors(include_url=False)[:3],
            raw,
        )
        return False

    async with engine.begin() as conn:
        await queries.lock_pair(conn, event.warehouse, event.sku)
        await queries.refresh_stock_agg(conn, event.warehouse, event.sku)
    logger.info(
        "stock_agg updated: %s/%s (event %s)",
        event.warehouse,
        event.sku,
        event.event_id,
    )
    return True


async def run_worker(
    engine: AsyncEngine,
    redis: aioredis.Redis,
    stop: asyncio.Event | None = None,
    ready: asyncio.Event | None = None,
) -> None:
    """Основной цикл. Переподключается к Redis при обрыве соединения"""
    stop = stop or asyncio.Event()
    while not stop.is_set():
        pubsub = redis.pubsub()
        try:
            await pubsub.subscribe(*CHANNELS)
            logger.info("subscribed to %s", ", ".join(CHANNELS))
            if ready is not None:
                ready.set()
            while not stop.is_set():
                msg = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if msg is None:
                    continue
                try:
                    await process_message(engine, msg["data"])
                except Exception:
                    logger.exception(
                        "failed to process message %r", msg.get("data")
                    )
        except redis_exc.RedisError:
            logger.exception("redis error, reconnecting in 1s")
            await asyncio.sleep(1)
        finally:
            try:
                await pubsub.aclose()
            except (redis_exc.RedisError, OSError):
                logger.debug("error while closing pubsub", exc_info=True)
