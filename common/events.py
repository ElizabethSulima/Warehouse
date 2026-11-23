"""Контракт событий, которыми обмениваются сервисы через Redis pub/sub."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

EventType = Literal["receipt", "issue"]
CHANNEL_RECEIPT = "inventory.receipt"
CHANNEL_ISSUE = "inventory.issue"
CHANNELS = (CHANNEL_RECEIPT, CHANNEL_ISSUE)
CHANNEL_BY_TYPE: dict[EventType, str] = {
    "receipt": CHANNEL_RECEIPT,
    "issue": CHANNEL_ISSUE,
}

Code = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
]
PositiveQty = Annotated[int, Field(gt=0, strict=True)]


class OperationIn(BaseModel):
    """Тело POST /receipts и POST /issues"""

    sku: Code
    qty: PositiveQty
    warehouse: Code


class InventoryEvent(BaseModel):
    """Сообщение в Redis"""

    event_id: int
    event_type: EventType
    sku: Code
    warehouse: Code
    qty: PositiveQty
    occurred_at: datetime
