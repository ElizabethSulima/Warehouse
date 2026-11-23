import json
from datetime import UTC, datetime

import sqlalchemy as sa

from analytics_worker.worker import process_message
from common import queries
from common.database import stock_agg


async def _add_event(engine, event_type, qty, wh="WH-1", sku="A-100"):
    async with engine.begin() as conn:
        row = await queries.insert_event(conn, event_type, wh, sku, qty)
    return json.dumps(
        {
            "event_id": row.id,
            "event_type": event_type,
            "sku": sku,
            "warehouse": wh,
            "qty": qty,
            "occurred_at": datetime.now(UTC).isoformat(),
        }
    )


async def _agg(engine):
    async with engine.connect() as conn:
        return (
            await conn.execute(
                sa.select(
                    stock_agg.c.warehouse, stock_agg.c.sku, stock_agg.c.qty
                )
            )
        ).all()


async def test_message_updates_single_row(engine):
    m1 = await _add_event(engine, "receipt", 50)
    assert await process_message(engine, m1) is True
    m2 = await _add_event(engine, "issue", 20)
    assert await process_message(engine, m2) is True

    rows = await _agg(engine)
    assert len(rows) == 1
    assert (rows[0].warehouse, rows[0].sku, rows[0].qty) == (
        "WH-1",
        "A-100",
        30,
    )


async def test_duplicate_delivery_is_idempotent(engine):
    m = await _add_event(engine, "receipt", 7)
    await process_message(engine, m)
    await process_message(engine, m)
    assert [r.qty for r in await _agg(engine)] == [7]


async def test_invalid_message_is_skipped(engine):
    assert await process_message(engine, "not json") is False
    assert await process_message(engine, json.dumps({"sku": "A"})) is False
    bad_type = {
        "event_id": 1,
        "event_type": "oops",
        "sku": "A",
        "warehouse": "W",
        "qty": 1,
        "occurred_at": "2024-01-01T00:00:00Z",
    }
    assert await process_message(engine, json.dumps(bad_type)) is False
    assert await _agg(engine) == []
