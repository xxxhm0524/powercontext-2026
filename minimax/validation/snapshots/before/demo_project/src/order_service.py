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
    """Return orders in newest-first order.

    ``status`` and ``min_total`` are accepted by the public interface but are
    not applied yet; implementing them is the task described in specs.
    """

    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer between 1 and 100")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise ValueError("offset must be a non-negative integer")

    ordered = sorted(orders, key=lambda order: (order.created_at, order.order_id), reverse=True)
    return ordered[offset : offset + limit]


def summarize_by_status(orders: Iterable[Order]) -> dict[str, int]:
    """Count orders by status; used by the dashboard and regression tests."""

    summary: dict[str, int] = {}
    for order in orders:
        summary[order.status] = summary.get(order.status, 0) + 1
    return summary
