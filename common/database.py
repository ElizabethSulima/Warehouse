"""Описание таблиц (SQLAlchemy Core, без ORM)."""

import sqlalchemy as sa

metadata = sa.MetaData()

stock_events = sa.Table(
    "stock_events",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("event_type", sa.String(16), nullable=False),  # receipt | issue
    sa.Column("sku", sa.String(64), nullable=False),
    sa.Column("warehouse", sa.String(64), nullable=False),
    sa.Column("qty", sa.Integer, nullable=False),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),  # pylint: disable=E1102
    ),
    sa.Index("ix_stock_events_wh_sku", "warehouse", "sku"),
)

stock_agg = sa.Table(
    "stock_agg",
    metadata,
    sa.Column("warehouse", sa.String(64), primary_key=True),
    sa.Column("sku", sa.String(64), primary_key=True),
    sa.Column("qty", sa.BigInteger, nullable=False),
    sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),  # pylint: disable=E1102
    ),
)
