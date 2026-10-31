"""Static checks for the bundled Dify DSL.

This is intentionally dependency-light: it verifies the graph shape, variable
references, HTTP body wiring and the absence of credentials before the DSL is
imported into a real Dify instance.  It does not replace a real Dify run; see
``validation.md`` for the end-to-end procedure.

Run:

    python tools/validate_dsl.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DSL = ROOT / "dsl" / "memory-tavern.yml"
EXPECTED_NODES = ["start", "http-request", "llm", "http-request", "answer"]
REFERENCE = re.compile(r"\{\{#([^#}]+)#\}\}")
SECRET = re.compile(r"(sk-[A-Za-z0-9]{10,}|github_pat_[A-Za-z0-9_]+|Bearer\s+[A-Za-z0-9._-]{20,})")


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def main() -> None:
    text = DSL.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        fail("DSL root must be a mapping")
    if data.get("kind") != "app":
        fail("kind must be 'app'")
    if str(data.get("version")) != "0.1.5":
        fail(f"expected DSL version 0.1.5, got {data.get('version')!r}")
    if data.get("app", {}).get("mode") != "advanced-chat":
        fail("app.mode must be 'advanced-chat'")

    graph = data["workflow"]["graph"]
    nodes = graph["nodes"]
    edges = graph["edges"]
    node_types = [node["data"]["type"] for node in nodes]
    if node_types != EXPECTED_NODES:
        fail(f"node order/types mismatch: {node_types}")

    ids = {node["id"] for node in nodes}
    for edge in edges:
        if edge["source"] not in ids or edge["target"] not in ids:
            fail(f"edge refers to a missing node: {edge}")
    if len(edges) != len(nodes) - 1:
        fail("graph should be a single linear chain")

    refs = sorted(set(REFERENCE.findall(text)))
    for ref in refs:
        node_id = ref.split(".", 1)[0]
        if node_id != "sys" and node_id not in ids:
            fail(f"variable reference to missing node: {ref}")
    if "sys.user_id" not in refs or "sys.query" not in refs:
        fail("DSL must use sys.user_id and sys.query")

    http_nodes = [node for node in nodes if node["data"]["type"] == "http-request"]
    for node in http_nodes:
        body = node["data"]["body"]
        if body["type"] != "form-data":
            fail(f"{node['data']['title']} should use form-data")
        keys = {item["key"] for item in body["data"]}
        if node["data"]["title"] == "召回记忆" and keys != {"player_id", "query"}:
            fail(f"recall fields mismatch: {keys}")
        if node["data"]["title"] == "记住这一轮" and keys != {
            "player_id",
            "user_message",
            "assistant_reply",
        }:
            fail(f"remember fields mismatch: {keys}")

    if SECRET.search(text):
        fail("DSL appears to contain a credential")

    print("DSL CHECK PASSED")
    print(f"  file      : {DSL.relative_to(ROOT)}")
    print(f"  mode      : {data['app']['mode']}")
    print(f"  nodes     : {' -> '.join(node_types)}")
    print(f"  references: {', '.join(refs)}")
    print("  secrets   : none")


if __name__ == "__main__":
    main()
