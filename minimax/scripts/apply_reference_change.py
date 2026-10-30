"""Apply the reference code change to a clean copy of the before snapshot."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sdd_context.dev_workflow import apply_diff, copy_before_snapshot


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default=str(ROOT / "validation" / "workspace-reference"))
    args = parser.parse_args()
    workspace = Path(args.workspace).resolve()
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    project = copy_before_snapshot(ROOT / "validation" / "snapshots" / "before" / "demo_project", workspace / "demo_project")
    diff = (ROOT / "validation" / "reference_change.patch").read_text(encoding="utf-8")
    result = apply_diff(project, diff, diff_path=workspace / "reference_change.patch")
    print(f"workspace: {project}")
    print(f"applied: {result.applied}")
    if not result.applied:
        print(result.stderr, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
