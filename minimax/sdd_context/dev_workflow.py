"""MiniMax-assisted development workflow for the SDD sample.

The workflow is deliberately explicit:

1. The seekdb selector builds a context bundle for the task.
2. The prompt embeds that bundle plus full source files from the before snapshot.
3. MiniMax returns a unified diff.
4. The diff is applied to a clean workspace and both target and regression tests
   are executed.

The transcript written by ``MiniMaxClient`` is the development record required
by the competition submission.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import ContextBundle

_DIFF_FENCE = re.compile(r"```(?:diff|patch)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


@dataclass
class PatchResult:
    applied: bool
    exit_code: int
    stdout: str
    stderr: str
    diff_path: str


def build_dev_prompt(bundle: ContextBundle, *, task_title: str, task_description: str, before_root: Path) -> tuple[str, list[dict[str, str]]]:
    """Return (system_prompt, messages) for the coding model."""

    lines: list[str] = []
    lines.append("你是一名使用 MiniMax 模型的 AI 开发助手。请基于严格给出的工程上下文完成代码修改。")
    lines.append("")
    lines.append("## 开发任务")
    lines.append(f"标题：{task_title}")
    lines.append(task_description.strip())
    lines.append("")
    lines.append("## 必须遵守的规格")
    for spec in bundle.specs:
        lines.append(f"### {spec.symbol} — {spec.title}")
        lines.append(spec.excerpt)
        lines.append("")
    lines.append("## 相关代码与测试来源")
    for item in bundle.code + bundle.tests:
        if item.symbol == "<module>":
            continue
        lines.append(f"- {item.kind}: {item.source_path}:{item.start_line}-{item.end_line} {item.symbol}")
    lines.append("")
    lines.append("## 完整文件（修改前）")
    seen_paths: set[str] = set()
    for item in bundle.code:
        if item.source_path in seen_paths:
            continue
        path = before_root / item.source_path
        if not path.is_file():
            continue
        seen_paths.add(item.source_path)
        lines.append(f"### {item.source_path}")
        language = "python" if path.suffix == ".py" else "text"
        lines.append(f"```{language}")
        lines.append(path.read_text(encoding="utf-8"))
        lines.append("```")
        lines.append("")
    for item in bundle.tests:
        if item.source_path in seen_paths:
            continue
        path = before_root / item.source_path
        if not path.is_file():
            continue
        seen_paths.add(item.source_path)
        lines.append(f"### {item.source_path}")
        lines.append("```python")
        lines.append(path.read_text(encoding="utf-8"))
        lines.append("```")
        lines.append("")
    lines.append("## 任务状态（PowerContext）")
    if bundle.state:
        lines.append(json.dumps(bundle.state.to_dict(), ensure_ascii=False, indent=2))
    else:
        lines.append("（空状态）")
    lines.append("")
    lines.append("## 输出要求")
    lines.append("- 只输出一个 unified diff，放在 ```diff 代码块中。")
    lines.append("- diff 必须能以 `git apply -p1` 从项目根目录应用。")
    lines.append("- 不得修改测试文件，不得删除或跳过断言。")
    lines.append("- 只实现上述规格要求的最小改动。")
    lines.append("")

    system = "你是一名严谨的 AI 编程助手，只输出可应用到指定工程的 unified diff。"
    user = "\n".join(lines)
    return system, [{"role": "user", "content": user}]


def extract_diff(response_text: str) -> str:
    fenced = _DIFF_FENCE.search(response_text)
    if fenced:
        candidate = fenced.group(1).strip()
        if candidate:
            return candidate + "\n"
    index = response_text.find("diff --git")
    if index >= 0:
        return response_text[index:].strip() + "\n"
    raise ValueError("MiniMax response did not contain a unified diff")


def apply_diff(workspace_root: Path, diff_text: str, *, diff_path: Path | None = None) -> PatchResult:
    workspace_root = workspace_root.resolve()
    diff_path = (diff_path or workspace_root.parent / "candidate.patch").resolve()
    diff_path.write_text(diff_text, encoding="utf-8", newline="\n")

    # GNU patch handles untracked demo projects predictably; git apply is a
    # fallback for environments without the patch utility.
    import shutil

    patch_binary = shutil.which("patch")
    if patch_binary:
        check = subprocess.run(
            [patch_binary, "-p1", "--dry-run", "--batch", "--forward", "--no-backup-if-mismatch", "-i", str(diff_path)],
            cwd=workspace_root,
            capture_output=True,
            text=True,
        )
        if check.returncode != 0:
            return PatchResult(False, check.returncode, check.stdout, check.stderr, str(diff_path))
        applied = subprocess.run(
            [patch_binary, "-p1", "--batch", "--forward", "--no-backup-if-mismatch", "-i", str(diff_path)],
            cwd=workspace_root,
            capture_output=True,
            text=True,
        )
        return PatchResult(applied.returncode == 0, applied.returncode, applied.stdout, applied.stderr, str(diff_path))

    check = subprocess.run(
        ["git", "apply", "--check", "--whitespace=nowarn", str(diff_path)],
        cwd=workspace_root,
        capture_output=True,
        text=True,
    )
    if check.returncode != 0:
        return PatchResult(False, check.returncode, check.stdout, check.stderr, str(diff_path))
    applied = subprocess.run(
        ["git", "apply", "--whitespace=nowarn", str(diff_path)],
        cwd=workspace_root,
        capture_output=True,
        text=True,
    )
    return PatchResult(applied.returncode == 0, applied.returncode, applied.stdout, applied.stderr, str(diff_path))


def copy_before_snapshot(before_root: Path, workspace_root: Path) -> Path:
    if workspace_root.exists():
        shutil.rmtree(workspace_root)
    shutil.copytree(before_root, workspace_root)
    return workspace_root


def run_pytest(workspace_root: Path, *, target: str | None = None, timeout: int = 120) -> dict[str, Any]:
    command = [sys.executable, "-m", "pytest", "-q", "--disable-warnings"]
    if target:
        command.append(target)
    started = time.perf_counter()
    completed = subprocess.run(command, cwd=workspace_root, capture_output=True, text=True, timeout=timeout)
    return {
        "command": " ".join(command),
        "cwd": str(workspace_root),
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        "timestamp": _now(),
    }


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def run_before_after(workspace_root: Path) -> dict[str, Any]:
    """Run target tests (expected to fail before) and regression tests."""

    target_before = run_pytest(workspace_root, target="tests/test_orders_filters.py")
    regression_before = run_pytest(workspace_root, target="tests/test_orders_regression.py")
    return {"target_before": target_before, "regression_before": regression_before}


def run_after_checks(workspace_root: Path) -> dict[str, Any]:
    target_after = run_pytest(workspace_root, target="tests/test_orders_filters.py")
    regression_after = run_pytest(workspace_root, target="tests/test_orders_regression.py")
    full_after = run_pytest(workspace_root)
    return {
        "target_after": target_after,
        "regression_after": regression_after,
        "full_after": full_after,
    }
