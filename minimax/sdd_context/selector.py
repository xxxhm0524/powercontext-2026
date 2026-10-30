"""Context selection over the seekdb material index."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import ContextBundle, SelectedSource, TaskState
from .seekdb_store import SearchRow, SeekDBMaterialStore
from .tokenization import query_terms

_KIND_ORDER = {"spec": 0, "code": 1, "test": 2}
_KIND_BONUS = {"spec": 0.35, "code": 0.25, "test": 0.2}
_SPEC_ID = re.compile(r"SPEC-[A-Z0-9-]+")


def _keyword_hits(text: str, terms: list[str]) -> tuple[int, list[str]]:
    lowered = text.lower()
    hits: list[str] = []
    for term in terms:
        if len(term) < 2:
            continue
        if term in lowered:
            hits.append(term)
    return len(set(hits)), sorted(set(hits), key=lambda item: (-len(item), item))[:8]


def _score_row(row: SearchRow, terms: list[str], query: str) -> tuple[float, list[str]]:
    chunk = row.chunk
    reasons: list[str] = []
    score = float(row.matched_terms) * 1.0 + min(float(row.term_hits), 30.0) * 0.02
    score += _KIND_BONUS.get(chunk.kind, 0.0)

    title_hits, title_terms = _keyword_hits(chunk.title, terms)
    symbol_hits, symbol_terms = _keyword_hits(chunk.symbol, terms)
    path_hits, path_terms = _keyword_hits(chunk.source_path, terms)
    if title_hits:
        score += 1.2 * title_hits
        reasons.append("title:" + ",".join(title_terms))
    if symbol_hits:
        score += 1.5 * symbol_hits
        reasons.append("symbol:" + ",".join(symbol_terms))
    if path_hits:
        score += 0.4 * path_hits
        reasons.append("path:" + ",".join(path_terms))

    # Exact spec IDs mentioned in the task are authoritative.
    spec_ids = _SPEC_ID.findall(query)
    if chunk.kind == "spec" and chunk.symbol in spec_ids:
        score += 12.0
        reasons.append("exact-spec-id")
    if chunk.metadata.get("spec_id") in spec_ids:
        score += 6.0
        reasons.append("metadata-spec-id")

    # Tests tagged to the same specs are useful even when word overlap is low.
    target_specs = chunk.metadata.get("target_specs") or []
    if chunk.kind == "test" and isinstance(target_specs, list):
        overlap = {str(item) for item in target_specs} & set(spec_ids)
        if overlap:
            score += 2.5 * len(overlap)
            reasons.append("targets:" + ",".join(sorted(overlap)))
        if chunk.metadata.get("regression"):
            score += 0.5
            reasons.append("regression")

    # Multi-term coverage is more important than repeated occurrences.
    coverage = row.matched_terms / max(1, min(len(terms), 25))
    score += coverage * 2.0
    reasons.append(f"matched={row.matched_terms}")
    return score, reasons


def _fallback_score(chunk, terms: list[str], query: str) -> tuple[float, list[str]]:
    text = chunk.title + "\n" + chunk.symbol + "\n" + chunk.content
    hits, matched = _keyword_hits(text, terms)
    reasons = [f"fallback_hits={hits}"]
    score = hits * 1.0
    if chunk.kind == "spec" and chunk.symbol in _SPEC_ID.findall(query):
        score += 12.0
        reasons.append("exact-spec-id")
    return score, reasons


def _to_source(row: SearchRow, score: float, reasons: list[str]) -> SelectedSource:
    chunk = row.chunk
    excerpt = chunk.content if len(chunk.content) <= 900 else chunk.content[:900] + "\n..."
    return SelectedSource(
        kind=chunk.kind,
        source_path=chunk.source_path,
        symbol=chunk.symbol,
        title=chunk.title,
        start_line=chunk.start_line,
        end_line=chunk.end_line,
        score=round(score, 4),
        reasons=reasons,
        excerpt=excerpt,
    )


def _dedupe(items: list[SelectedSource], limit: int) -> list[SelectedSource]:
    out: list[SelectedSource] = []
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        key = (item.kind, item.source_path, item.symbol)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def select_context(
    store: SeekDBMaterialStore,
    *,
    task_id: str,
    query: str,
    project_root: Path,
    state: TaskState | None = None,
    max_specs: int = 7,
    max_code: int = 8,
    max_tests: int = 12,
) -> ContextBundle:
    terms = query_terms(query)
    rows = store.search(terms, limit=400, task=query)
    all_chunks = {chunk.chunk_id: chunk for chunk in store.fetch_all()}

    by_kind: dict[str, list[tuple[float, list[str], SearchRow | Any]]] = {"spec": [], "code": [], "test": []}
    seen_ids: set[str] = set()
    for row in rows:
        score, reasons = _score_row(row, terms, query)
        by_kind.setdefault(row.chunk.kind, []).append((score, reasons, row))
        seen_ids.add(row.chunk.chunk_id)

    # Fill gaps with a local lexical fallback over the same DB corpus.  This
    # matters for short files where the SQL index returns fewer than N rows.
    for chunk_id, chunk in all_chunks.items():
        if chunk_id in seen_ids:
            continue
        score, reasons = _fallback_score(chunk, terms, query)
        if score > 0:
            dummy = SearchRow(chunk=chunk, matched_terms=0, term_hits=0, sql_score=0.0)
            by_kind.setdefault(chunk.kind, []).append((score, reasons, dummy))

    selected: dict[str, list[SelectedSource]] = {"spec": [], "code": [], "test": []}
    for kind, candidates in by_kind.items():
        candidates.sort(key=lambda item: item[0], reverse=True)
        selected[kind] = [
            _to_source(row, score, reasons)
            for score, reasons, row in candidates
            if row is not None
        ]

    specs = _dedupe(selected["spec"], max_specs)
    code = _dedupe(selected["code"], max_code)
    tests = _dedupe(selected["test"], max_tests)

    # Make sure the module that owns the primary code symbol appears alongside
    # the symbol chunk; it provides imports and constants needed for a patch.
    module_chunks = [
        item
        for item in selected["code"]
        if item.symbol == "<module>" and item.source_path in {entry.source_path for entry in code}
    ]
    code = _dedupe(module_chunks + code, max_code + 1)

    sources: list[SelectedSource] = []
    seen_sources: set[tuple[str, str, str]] = set()
    for item in specs + code + tests:
        key = (item.kind, item.source_path, item.symbol)
        if key in seen_sources:
            continue
        seen_sources.add(key)
        sources.append(item)

    bundle = ContextBundle(
        task_id=task_id,
        query=query,
        project_root=str(project_root),
        generated_at=datetime.now(UTC).isoformat(),
        specs=specs,
        code=code,
        tests=tests,
        state=state,
        sources=sources,
        stats={
            "query_terms": terms[:40],
            "candidate_rows": len(rows),
            "indexed_chunks": len(all_chunks),
            "selected": {"specs": len(specs), "code": len(code), "tests": len(tests)},
            "store_mode": store.mode,
        },
    )
    return bundle


def render_markdown(bundle: ContextBundle) -> str:
    lines: list[str] = []
    lines.append(f"# 开发上下文 · {bundle.task_id}")
    lines.append("")
    lines.append(f"**任务**：{bundle.query}")
    lines.append("")
    lines.append("## 适用规格")
    for item in bundle.specs:
        lines.append(f"- `{item.symbol}` {item.title} — `{item.source_path}:{item.start_line}-{item.end_line}`")
    lines.append("")
    lines.append("## 相关代码")
    for item in bundle.code:
        if item.symbol == "<module>":
            continue
        lines.append(f"- `{item.symbol}` — `{item.source_path}:{item.start_line}-{item.end_line}`")
    lines.append("")
    lines.append("## 验证测试")
    for item in bundle.tests:
        lines.append(f"- `{item.symbol}` — `{item.source_path}:{item.start_line}-{item.end_line}`")
    lines.append("")
    if bundle.state:
        lines.append("## 任务状态（PowerContext）")
        lines.append(f"- status: `{bundle.state.status}`")
        lines.append(f"- completed: {', '.join(bundle.state.completed) or '—'}")
        lines.append(f"- todo: {', '.join(bundle.state.todo) or '—'}")
        lines.append(f"- verification: `{bundle.state.verification}`")
    return "\n".join(lines) + "\n"
