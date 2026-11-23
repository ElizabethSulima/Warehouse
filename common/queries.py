"""Все SQL-запросы (SQLAlchemy Core поверх asyncpg)."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from common.database import stock_agg
from common.database import stock_events as se


def signed_qty():
    """+qty для поступления, -qty для расхода"""
    return sa.case((se.c.event_type == "receipt", se.c.qty), else_=-se.c.qty)


async def lock_pair(conn: AsyncConnection, warehouse: str, sku: str) -> None:
    """Транзакционный advisory-lock на пару (warehouse, sku)

    Защищает от гонок: два одновременных расхода не уведут остаток в минус,
    а пересчёт агрегата в воркере не перепишет более свежее значение старым.
    """
    await conn.execute(
        sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"{warehouse}|{sku}"},
    )


async def get_balance(conn: AsyncConnection, warehouse: str, sku: str) -> int:
    stmt = sa.select(sa.func.coalesce(sa.func.sum(signed_qty()), 0)).where(
        se.c.warehouse == warehouse, se.c.sku == sku
    )
    return int((await conn.execute(stmt)).scalar_one())


async def insert_event(
    conn: AsyncConnection, event_type: str, warehouse: str, sku: str, qty: int
):
    stmt = (
        sa.insert(se)
        .values(event_type=event_type, warehouse=warehouse, sku=sku, qty=qty)
        .returning(se.c.id, se.c.created_at)
    )
    return (await conn.execute(stmt)).one()


def _balances(warehouse: str | None = None, sku: str | None = None):
    """
    Подзапрос: остатки по парам (warehouse, sku) — GROUP BY по журналу операций
    """
    stmt = sa.select(
        se.c.warehouse, se.c.sku, sa.func.sum(signed_qty()).label("qty")
    ).group_by(se.c.warehouse, se.c.sku)
    if warehouse is not None:
        stmt = stmt.where(se.c.warehouse == warehouse)
    if sku is not None:
        stmt = stmt.where(se.c.sku == sku)
    return stmt.subquery("balances")


async def get_stock(
    conn: AsyncConnection, warehouse: str, sku: str | None = None
):
    b = _balances(warehouse, sku)
    stmt = sa.select(b.c.sku, b.c.qty).order_by(b.c.sku)
    if sku is None:
        stmt = stmt.where(b.c.qty > 0)
    rows = (await conn.execute(stmt)).all()
    return [{"sku": r.sku, "qty": int(r.qty)} for r in rows]


async def get_summary(conn: AsyncConnection, top_n: int = 5) -> dict:
    b = _balances()

    warehouses_stmt = (
        sa.select(
            b.c.warehouse,
            sa.cast(sa.func.sum(b.c.qty), sa.BigInteger).label("total_qty"),
            sa.func.count(b.c.sku).label("sku_count"),  # pylint: disable=E1102
        )
        .where(b.c.qty > 0)
        .group_by(b.c.warehouse)
        .order_by(b.c.warehouse)
    )
    top_stmt = (
        sa.select(
            b.c.sku,
            sa.cast(sa.func.sum(b.c.qty), sa.BigInteger).label("total_qty"),
        )
        .where(b.c.qty > 0)
        .group_by(b.c.sku)
        .order_by(sa.desc("total_qty"), b.c.sku)
        .limit(top_n)
    )
    wh_rows = (await conn.execute(warehouses_stmt)).all()
    top_rows = (await conn.execute(top_stmt)).all()
    return {
        "warehouses": [
            {
                "warehouse": r.warehouse,
                "total_qty": int(r.total_qty),
                "sku_count": int(r.sku_count),
            }
            for r in wh_rows
        ],
        "top_skus": [
            {"sku": r.sku, "total_qty": int(r.total_qty)} for r in top_rows
        ],
    }


async def refresh_stock_agg(
    conn: AsyncConnection, warehouse: str, sku: str
) -> None:
    """UPSERT остатка пары в stock_agg (строка обновляется, а не добавляется).

    Значение пересчитывается подзапросом из журнала, поэтому обработка
    идемпотентна: повторная доставка события не удвоит остаток.
    """
    total = (
        sa.select(sa.func.coalesce(sa.func.sum(signed_qty()), 0))
        .where(se.c.warehouse == warehouse, se.c.sku == sku)
        .scalar_subquery()
    )
    ins = pg_insert(stock_agg).values(
        warehouse=warehouse,
        sku=sku,
        qty=total,
        updated_at=sa.func.now(),  # pylint: disable=E1102
    )
    stmt = ins.on_conflict_do_update(
        index_elements=[stock_agg.c.warehouse, stock_agg.c.sku],
        set_={
            "qty": ins.excluded.qty,
            "updated_at": sa.func.now(),  # pylint: disable=E1102
        },
    )
    await conn.execute(stmt)
