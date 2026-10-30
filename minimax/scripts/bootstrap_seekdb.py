"""Create a free seven-day seekdb instance and persist its connection DSN.

The competition task accepts seekdb Server or OceanBase.  For reviewers who do
not have a local installation, the public seekdb playground can be bootstrapped
with one HTTP call (no account needed).  The credentials are written to
``minimax/.runtime/seekdb.json`` (git-ignored).

Usage::

    python scripts/bootstrap_seekdb.py
    python scripts/bootstrap_seekdb.py --print-only
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sdd_context.config import ensure_runtime_dirs, runtime_dir


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default="https://d0.seekdb.ai/api/v1/instances")
    parser.add_argument("--print-only", action="store_true")
    args = parser.parse_args()

    response = httpx.post(args.endpoint, timeout=60)
    response.raise_for_status()
    payload = response.json()
    required = {"instance_id", "username", "password", "database", "host", "port"}
    missing = required - set(payload)
    if missing:
        print(f"Unexpected response, missing: {sorted(missing)}", file=sys.stderr)
        print(json.dumps(payload, ensure_ascii=False)[:1000], file=sys.stderr)
        return 2

    connection = (
        f"mysql://{payload['username']}:{payload['password']}@"
        f"{payload['host']}:{payload['port']}/{payload['database']}"
    )
    record = {
        "instance_id": payload["instance_id"],
        "connection": connection,
        "expires_at": payload.get("expires_at"),
        "created_at": payload.get("created_at", ""),
        "raw": payload,
    }
    print(json.dumps(record, ensure_ascii=False, indent=2))
    if not args.print_only:
        ensure_runtime_dirs()
        target = runtime_dir() / "seekdb.json"
        target.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nSaved to {target}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
