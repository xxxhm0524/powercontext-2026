"""Target tests for the new status / minimum-amount filters.

These tests describe the behaviour required by the task and intentionally fail
against the before snapshot because the two filters are not implemented yet.
"""

from __future__ import annotations

import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from order_service import Order, list_orders


def make_orders() -> list[Order]:
    return [
        Order("O-1001", "alice", "paid", Decimal("120.00"), datetime(2026, 10, 1, 9, 0)),
        Order("O-1002", "bob", "pending", Decimal("80.50"), datetime(2026, 10, 2, 10, 0)),
        Order("O-1003", "carol", "paid", Decimal("45.00"), datetime(2026, 10, 3, 11, 0)),
        Order("O-1004", "dave", "shipped", Decimal("300.00"), datetime(2026, 10, 4, 12, 0)),
        Order("O-1005", "eve", "cancelled", Decimal("20.00"), datetime(2026, 10, 5, 13, 0)),
    ]


def test_filter_by_status_returns_only_matching() -> None:
    """TARGET_SPECS: SPEC-ORD-002"""

    result = list_orders(make_orders(), status="paid")
    assert [order.order_id for order in result] == ["O-1003", "O-1001"]


def test_filter_by_min_total_excludes_smaller() -> None:
    """TARGET_SPECS: SPEC-ORD-003"""

    result = list_orders(make_orders(), min_total=Decimal("80.50"))
    assert [order.order_id for order in result] == ["O-1004", "O-1002", "O-1001"]


def test_filter_combined_intersection_and_order() -> None:
    """TARGET_SPECS: SPEC-ORD-005"""

    result = list_orders(make_orders(), status="paid", min_total=Decimal("50"))
    assert [order.order_id for order in result] == ["O-1001"]


def test_invalid_status_rejected() -> None:
    """TARGET_SPECS: SPEC-ORD-002"""

    with pytest.raises(ValueError):
        list_orders(make_orders(), status="refunded")


def test_negative_min_total_rejected() -> None:
    """TARGET_SPECS: SPEC-ORD-003"""

    with pytest.raises(ValueError):
        list_orders(make_orders(), min_total=Decimal("-0.01"))
