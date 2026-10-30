"""Regression tests: behaviour that must survive the filter change."""

from __future__ import annotations

import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from order_service import Order, list_orders, summarize_by_status


def make_orders() -> list[Order]:
    return [
        Order("O-1001", "alice", "paid", Decimal("120.00"), datetime(2026, 10, 1, 9, 0)),
        Order("O-1002", "bob", "pending", Decimal("80.50"), datetime(2026, 10, 2, 10, 0)),
        Order("O-1003", "carol", "paid", Decimal("45.00"), datetime(2026, 10, 3, 11, 0)),
        Order("O-1004", "dave", "shipped", Decimal("300.00"), datetime(2026, 10, 4, 12, 0)),
        Order("O-1005", "eve", "cancelled", Decimal("20.00"), datetime(2026, 10, 5, 13, 0)),
    ]


def test_default_sort_is_newest_first() -> None:
    """REGRESSION: true
    TARGET_SPECS: SPEC-ORD-001
    """

    result = list_orders(make_orders(), limit=3)
    assert [order.order_id for order in result] == ["O-1005", "O-1004", "O-1003"]


def test_pagination_preserves_order() -> None:
    """REGRESSION: true
    TARGET_SPECS: SPEC-ORD-004
    """

    first = list_orders(make_orders(), limit=2, offset=0)
    second = list_orders(make_orders(), limit=2, offset=2)
    assert [order.order_id for order in first] == ["O-1005", "O-1004"]
    assert [order.order_id for order in second] == ["O-1003", "O-1002"]


def test_invalid_limit_rejected() -> None:
    """REGRESSION: true
    TARGET_SPECS: SPEC-ORD-004
    """

    with pytest.raises(ValueError):
        list_orders(make_orders(), limit=0)
    with pytest.raises(ValueError):
        list_orders(make_orders(), limit=101)


def test_negative_offset_rejected() -> None:
    """REGRESSION: true
    TARGET_SPECS: SPEC-ORD-004
    """

    with pytest.raises(ValueError):
        list_orders(make_orders(), offset=-1)


def test_status_summary_unchanged() -> None:
    """REGRESSION: true
    TARGET_SPECS: SPEC-ORD-001
    """

    assert summarize_by_status(make_orders()) == {"paid": 2, "pending": 1, "shipped": 1, "cancelled": 1}


def test_min_total_zero_is_no_amount_filter() -> None:
    """REGRESSION: true
    TARGET_SPECS: SPEC-ORD-003
    """

    assert len(list_orders(make_orders(), min_total=0)) == len(make_orders())

