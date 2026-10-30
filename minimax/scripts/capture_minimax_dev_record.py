"""Capture a real MiniMax development session for the SDD sample.

Usage (with a MiniMax platform key)::

    set MINIMAX_API_KEY=...
    python scripts/capture_minimax_dev_record.py \
        --context validation/context_before.json \
        --before-root validation/workspace/demo_project \
        --record records/minimax_dev_record.jsonl \
        --output-diff validation/minimax_output.diff

The resulting JSONL record contains the exact task, context bundle, prompt,
model response, usage and latency.  ``--fixture`` is only for offline pipeline
tests and is explicitly marked ``provider=fixture`` in the record.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sdd_context.dev_workflow import build_dev_prompt, extract_diff
from sdd_context.minimax_client import MiniMaxClient, MiniMaxConfig
from sdd_context.models import ContextBundle, SelectedSource, TaskState


def load_bundle(path: Path) -> ContextBundle:
    payload = json.loads(path.read_text(encoding="utf-8"))

    def sources(key: str) -> list[SelectedSource]:
        return [
            SelectedSource(
                kind=item["kind"],
                source_path=item["source_path"],
                symbol=item["symbol"],
                title=item["title"],
                start_line=int(item["start_line"]),
                end_line=int(item["end_line"]),
                score=float(item.get("score", 0)),
                reasons=list(item.get("reasons", [])),
                excerpt=item.get("excerpt", ""),
            )
            for item in payload.get(key, [])
        ]

    state_payload = payload.get("state")
    return ContextBundle(
        task_id=payload["task_id"],
        query=payload["query"],
        project_root=payload["project_root"],
        generated_at=payload.get("generated_at", ""),
        specs=sources("specs"),
        code=sources("code"),
        tests=sources("tests"),
        state=TaskState.from_dict(state_payload) if state_payload else None,
        sources=sources("sources"),
        stats=payload.get("stats", {}),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", required=True)
    parser.add_argument("--before-root", required=True)
    parser.add_argument("--record", default="records/minimax_dev_record.jsonl")
    parser.add_argument("--output-diff", default="validation/minimax_output.diff")
    parser.add_argument("--task-title", default="为订单列表增加状态与最低金额筛选")
    parser.add_argument(
        "--task-description",
        default=(
            "按照 specs/orders.md 的 SPEC-ORD-002、SPEC-ORD-003、SPEC-ORD-005，为 "
            "list_orders 增加 status 与 min_total 筛选，同时保持 SPEC-ORD-004 的分页与回归兼容。"
        ),
    )
    parser.add_argument("--fixture", default=None, help="offline fixture response; never used for final submission")
    parser.add_argument("--max-tokens", type=int, default=32000)
    args = parser.parse_args()

    bundle = load_bundle(Path(args.context))
    system, messages = build_dev_prompt(
        bundle,
        task_title=args.task_title,
        task_description=args.task_description,
        before_root=Path(args.before_root),
    )
    record_path = Path(args.record)
    record_path.parent.mkdir(parents=True, exist_ok=True)
    output_diff = Path(args.output_diff)
    output_diff.parent.mkdir(parents=True, exist_ok=True)

    if args.fixture:
        content = Path(args.fixture).read_text(encoding="utf-8")
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "purpose": "sdd-context-demo",
            "provider": "fixture",
            "api_style": "fixture",
            "model": "reference-patch",
            "prompt_sha256": "",
            "request": {"system": system, "messages": messages},
            "response": {"content": content, "usage": {}},
            "latency_ms": 0,
        }
        with record_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        output_diff.write_text(extract_diff(content), encoding="utf-8")
        print(f"Fixture record written to {record_path} (not a MiniMax record)")
        return 0

    client = MiniMaxClient(MiniMaxConfig.from_env(), record_path=record_path)
    try:
        result = client.chat(
            messages,
            system=system,
            max_tokens=args.max_tokens,
            purpose="sdd-context-demo",
        )
    finally:
        client.close()
    output_diff.write_text(extract_diff(result.content), encoding="utf-8")
    print(f"MiniMax record written to {record_path}")
    print(f"Patch written to {output_diff}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
