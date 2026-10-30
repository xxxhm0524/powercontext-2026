"""A tiny order-query business service used by the SDD demo.

The service is deliberately dependency-free so the reviewer can run it with a
stock Python interpreter.  Orders are supplied by the caller; persistence
belongs to the host application, not to the query helper.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable

VALID_STATUSES = ("pending", "paid", "shipped", "cancelled")


@dataclass(frozen=True)
class Order:
    order_id: str
    customer: str
    status: str
    total: Decimal
    created_at: datetime


def _coerce_min_total(value: Decimal | str | int) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError("min_total must be a decimal number") from error


def list_orders(
    orders: Iterable[Order],
    *,
    status: str | None = None,
    min_total: Decimal | str | int | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[Order]:
    """Return orders in newest-first order with optional status/min_total filters.

    Filtering is applied before pagination so page contents are stable.
    """

    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer between 1 and 100")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise ValueError("offset must be a non-negative integer")

    if status is not None and status not in VALID_STATUSES:
        raise ValueError(f"unknown status: {status}")

    threshold: Decimal | None = None
    if min_total is not None:
        threshold = _coerce_min_total(min_total)
        if threshold < 0:
            raise ValueError("min_total must be non-negative")

    ordered = sorted(orders, key=lambda order: (order.created_at, order.order_id), reverse=True)
    filtered = [
        order
        for order in ordered
        if (status is None or order.status == status)
        and (threshold is None or order.total >= threshold)
    ]
    return filtered[offset : offset + limit]


def summarize_by_status(orders: Iterable[Order]) -> dict[str, int]:
    """Count orders by status; used by the dashboard and regression tests."""

    summary: dict[str, int] = {}
    for order in orders:
        summary[order.status] = summary.get(order.status, 0) + 1
    return summary
