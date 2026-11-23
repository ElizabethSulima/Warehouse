"""
Сквозной тест: API -> Redis pub/sub -> воркер -> stock_agg
(реальные Postgres и Redis)
"""

import asyncio

import redis.asyncio as aioredis
import sqlalchemy as sa

from analytics_worker.worker import run_worker
from common.database import stock_agg
from tests.conftest import TEST_REDIS_URL


async def test_api_event_reaches_worker(client, engine):
    redis = aioredis.from_url(TEST_REDIS_URL, decode_responses=True)
    stop, ready = asyncio.Event(), asyncio.Event()
    task = asyncio.create_task(run_worker(engine, redis, stop, ready))
    try:
        await asyncio.wait_for(ready.wait(), 5)

        body = {"sku": "A-100", "warehouse": "WH-1"}
        assert (
            await client.post("/receipts", json={**body, "qty": 50})
        ).status == 201
        assert (
            await client.post("/issues", json={**body, "qty": 20})
        ).status == 201

        qty = None
        for _ in range(50):
            async with engine.connect() as conn:
                qty = (await conn.execute(sa.select(stock_agg.c.qty))).scalar()
            if qty == 30:
                break
            await asyncio.sleep(0.1)
        assert qty == 30
    finally:
        stop.set()
        await asyncio.wait_for(task, 5)
        await redis.aclose()
