"""A tiny order-query business service used by the SDD demo.

The service is deliberately dependency-free so the reviewer can run it with a
stock Python interpreter.  Orders are supplied by the caller; persistence
belongs to the host application, not to the query helper.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Iterable

VALID_STATUSES = ("pending", "paid", "shipped", "cancelled")


@dataclass(frozen=True)
class Order:
    order_id: str
    customer: str
    status: str
    total: Decimal
    created_at: datetime


def list_orders(
    orders: Iterable[Order],
    *,
    status: str | None = None,
    min_total: Decimal | str | int | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[Order]:
    """Return orders in newest-first order, optionally filtered."""

    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer between 1 and 100")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise ValueError("offset must be a non-negative integer")

    if status is not None and status not in VALID_STATUSES:
        raise ValueError("status must be one of: pending, paid, shipped, cancelled")

    minimum: Decimal | None = None
    if min_total is not None:
        minimum = Decimal(min_total) if isinstance(min_total, str) else Decimal(min_total)
        if minimum < 0:
            raise ValueError("min_total must be non-negative")

    filtered = [
        order
        for order in orders
        if (status is None or order.status == status)
        and (minimum is None or minimum == 0 or order.total >= minimum)
    ]
    ordered = sorted(orders, key=lambda order: (order.created_at, order.order_id), reverse=True)
    ordered = sorted(filtered, key=lambda order: (order.created_at, order.order_id), reverse=True)
    return ordered[offset : offset + limit]


def summarize_by_status(orders: Iterable[Order]) -> dict[str, int]:
    """Count orders by status; used by the dashboard and regression tests."""

    summary: dict[str, int] = {}
    for order in orders:
        summary[order.status] = summary.get(order.status, 0) + 1
    return summary
