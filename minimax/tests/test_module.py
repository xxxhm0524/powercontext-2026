"""Fast unit tests for the context module pieces that do not need a database."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sdd_context.corpus import load_corpus, parse_specs
from sdd_context.dev_workflow import extract_diff
from sdd_context.minimax_client import _extract_native_content
from sdd_context.tokenization import expand_terms, query_terms


def test_spec_parser_preserves_ids_and_ranges() -> None:
    project = ROOT / "demo_project"
    chunks = parse_specs(project / "specs" / "orders.md", root=project)
    assert [chunk.symbol for chunk in chunks] == [
        "SPEC-ORD-001",
        "SPEC-ORD-002",
        "SPEC-ORD-003",
        "SPEC-ORD-004",
        "SPEC-ORD-005",
    ]
    assert all(chunk.start_line <= chunk.end_line for chunk in chunks)


def test_corpus_includes_code_symbols_and_tests() -> None:
    chunks = load_corpus(ROOT / "demo_project")
    symbols = {(chunk.kind, chunk.symbol) for chunk in chunks}
    assert ("code", "list_orders") in symbols
    assert ("test", "test_filter_by_status_returns_only_matching") in symbols


def test_bilingual_terms_cover_domain_identifiers() -> None:
    terms = set(expand_terms("为订单列表增加按状态和最低金额筛选"))
    assert "status" in terms
    assert "min_total" in terms
    assert "list_orders" in terms


def test_query_terms_are_bounded_and_deterministic() -> None:
    terms = query_terms("为订单列表增加按状态和最低金额筛选，需保持分页兼容")
    assert terms == query_terms("为订单列表增加按状态和最低金额筛选，需保持分页兼容")
    assert len(terms) <= 120


def test_extract_diff_accepts_fenced_block() -> None:
    response = "说明\n```diff\ndiff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n```\n"
    assert extract_diff(response).startswith("diff --git")


def test_native_content_extraction() -> None:
    assert _extract_native_content({"choices": [{"message": {"content": "hello"}}]}) == "hello"
    assert _extract_native_content({"reply": "hello"}) == "hello"
