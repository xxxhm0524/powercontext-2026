"""SDD context module command line interface.

Examples::

    python -m sdd_context.cli init --project-root demo_project
    python -m sdd_context.cli context --task-id TASK-1 --query "为订单列表增加按状态和最低金额筛选"
    python -m sdd_context.cli state-save --task-id TASK-1 --status context_ready --completed task_defined
    python -m sdd_context.cli state-show --task-id TASK-1

The CLI is intentionally the stable integration surface.  ``scripts/http_server.py``
exposes the same selector through HTTP for agent/tool integrations.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from .config import ensure_runtime_dirs, project_root as default_project_root, records_dir, runtime_dir, state_db_path
from .corpus import load_corpus
from .models import TaskState
from .seekdb_store import SeekDBMaterialStore, default_query_log
from .selector import render_markdown, select_context
from .state import PowerContextStateStore


def _store(args: argparse.Namespace) -> SeekDBMaterialStore:
    query_log = Path(args.query_log) if getattr(args, "query_log", None) else default_query_log()
    store = SeekDBMaterialStore(
        dsn=getattr(args, "seekdb_dsn", None),
        embedded_path=Path(args.seekdb_path) if getattr(args, "seekdb_path", None) else None,
        query_log=query_log,
    )
    store.connect()
    return store


def _state_store(args: argparse.Namespace) -> PowerContextStateStore:
    db = Path(args.state_db) if getattr(args, "state_db", None) else state_db_path()
    log = records_dir() / "powercontext_state_record.jsonl"
    return PowerContextStateStore(db_path=db, project_id=getattr(args, "project_id", "sdd-order-demo"), log_path=log)


def cmd_init(args: argparse.Namespace) -> int:
    ensure_runtime_dirs()
    root = Path(args.project_root).resolve()
    chunks = load_corpus(root)
    if not chunks:
        print(f"No chunks found under {root}", file=sys.stderr)
        return 2
    with _store(args) as store:
        if args.reset:
            store.reset()
        result = store.import_chunks(chunks)
    print(json.dumps({"project_root": str(root), "import": result}, ensure_ascii=False, indent=2))
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    root = Path(args.project_root).resolve()
    state = None
    if not args.no_state:
        async def _load() -> TaskState | None:
            async with _state_store(args) as store:
                return await store.load(args.task_id)
        state = asyncio.run(_load())
    with _store(args) as store:
        bundle = select_context(
            store,
            task_id=args.task_id,
            query=args.query,
            project_root=root,
            state=state,
            max_specs=args.max_specs,
            max_code=args.max_code,
            max_tests=args.max_tests,
        )
    payload = bundle.to_dict()
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(text + "\n", encoding="utf-8")
    if args.markdown_out:
        Path(args.markdown_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.markdown_out).write_text(render_markdown(bundle), encoding="utf-8")
    print(text)
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    from .tokenization import query_terms

    terms = query_terms(args.query)
    with _store(args) as store:
        rows = store.search(terms, limit=args.limit, task=args.query)
        payload = [
            {
                "kind": row.chunk.kind,
                "source_path": row.chunk.source_path,
                "symbol": row.chunk.symbol,
                "matched_terms": row.matched_terms,
                "term_hits": row.term_hits,
            }
            for row in rows
        ]
    print(json.dumps({"terms": terms[:40], "rows": payload}, ensure_ascii=False, indent=2))
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    with _store(args) as store:
        payload = store.stats()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _parse_verification(value: str | None) -> dict | None:
    if value is None:
        return None
    path = Path(value)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return json.loads(value)


def cmd_state_save(args: argparse.Namespace) -> int:
    async def _save() -> dict:
        async with _state_store(args) as store:
            current = await store.load(args.task_id)
            state = current or TaskState(task_id=args.task_id)
            if args.status:
                state.status = args.status
            for item in args.completed or []:
                if item not in state.completed:
                    state.completed.append(item)
            if args.clear_todo:
                state.todo = []
            for item in args.todo or []:
                if item not in state.todo:
                    state.todo.append(item)
            verification = _parse_verification(args.verification)
            if verification is not None:
                state.verification = verification
            if args.notes is not None:
                state.notes = args.notes
            state.updated_at = datetime.now(UTC).isoformat()
            return await store.save(state)

    print(json.dumps(asyncio.run(_save()), ensure_ascii=False, indent=2))
    return 0


def cmd_state_show(args: argparse.Namespace) -> int:
    async def _show() -> dict:
        async with _state_store(args) as store:
            if args.all:
                states = await store.load_all()
                return {"states": [state.to_dict() for state in states]}
            state = await store.load(args.task_id)
            return {"state": state.to_dict() if state else None}

    print(json.dumps(asyncio.run(_show()), ensure_ascii=False, indent=2))
    return 0


def cmd_state_entries(args: argparse.Namespace) -> int:
    async def _entries() -> dict:
        async with _state_store(args) as store:
            return {"entries": await store.entries()}

    print(json.dumps(asyncio.run(_entries()), ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SDD engineering-context module")
    parser.add_argument("--project-id", default="sdd-order-demo")
    parser.add_argument("--seekdb-dsn", default=None)
    parser.add_argument("--seekdb-path", default=None)
    parser.add_argument("--state-db", default=None)
    parser.add_argument("--query-log", default=None)

    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="import specs/code/tests into seekdb")
    init.add_argument("--project-root", default=str(default_project_root()))
    init.add_argument("--reset", action="store_true")
    init.set_defaults(func=cmd_init)

    context = sub.add_parser("context", help="select the development context for a task")
    context.add_argument("--task-id", required=True)
    context.add_argument("--query", required=True)
    context.add_argument("--project-root", default=str(default_project_root()))
    context.add_argument("--json-out", default=None)
    context.add_argument("--markdown-out", default=None)
    context.add_argument("--max-specs", type=int, default=7)
    context.add_argument("--max-code", type=int, default=8)
    context.add_argument("--max-tests", type=int, default=12)
    context.add_argument("--no-state", action="store_true")
    context.set_defaults(func=cmd_context)

    search = sub.add_parser("search", help="show raw seekdb index hits")
    search.add_argument("--query", required=True)
    search.add_argument("--limit", type=int, default=50)
    search.set_defaults(func=cmd_search)

    stats = sub.add_parser("stats", help="show index statistics")
    stats.set_defaults(func=cmd_stats)

    save = sub.add_parser("state-save", help="append a task-state revision to PowerContext")
    save.add_argument("--task-id", required=True)
    save.add_argument("--status", default=None)
    save.add_argument("--completed", action="append", default=[])
    save.add_argument("--todo", action="append", default=[])
    save.add_argument("--clear-todo", action="store_true")
    save.add_argument("--verification", default=None, help="JSON object or path to JSON")
    save.add_argument("--notes", default=None)
    save.set_defaults(func=cmd_state_save)

    show = sub.add_parser("state-show", help="read task state from PowerContext")
    show.add_argument("--task-id", default="")
    show.add_argument("--all", action="store_true")
    show.set_defaults(func=cmd_state_show)

    entries = sub.add_parser("state-entries", help="dump all PowerContext memory entries")
    entries.set_defaults(func=cmd_state_entries)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    ensure_runtime_dirs()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
