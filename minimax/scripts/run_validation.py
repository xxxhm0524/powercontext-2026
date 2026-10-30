"""End-to-end acceptance run for the MiniMax SDD sample.

The script is intentionally self-contained: it copies the before snapshot into a
clean workspace, imports specs/code/tests into seekdb, exercises the context
module and PowerContext state in separate processes, applies the candidate
patch, runs target and regression tests, checks that a spec update is reflected
in the selected context, and writes machine-readable evidence.

Usage::

    python scripts/run_validation.py
    python scripts/run_validation.py --minimax-record records/minimax_dev_record.jsonl

If ``MINIMAX_API_KEY`` is present and ``--use-minimax`` is passed, the script
captures a fresh MiniMax development record and uses the model-produced patch.
Otherwise it uses ``validation/reference_change.patch`` and reports the
MiniMax-participation gate as failed (the other five gates are still tested).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sdd_context.config import _load_dotenv
from sdd_context.corpus import load_corpus
from sdd_context.dev_workflow import apply_diff, extract_diff, run_after_checks, run_before_after
from sdd_context.seekdb_store import SeekDBMaterialStore
from sdd_context.selector import select_context

RECORDS = ROOT / "records"
VALIDATION = ROOT / "validation"
SAMPLE_TASK = VALIDATION / "sample_task.json"
_load_dotenv()


def now() -> str:
    return datetime.now(UTC).isoformat()


def run_cli(args: list[str], *, state_db: Path, env: dict[str, str] | None = None) -> dict[str, Any]:
    command = [sys.executable, "-m", "sdd_context.cli", "--state-db", str(state_db), *args]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, env=env, timeout=180)
    return {
        "command": " ".join(command),
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "timestamp": now(),
    }


def pytest_counts(result: dict[str, Any]) -> dict[str, int]:
    text = result.get("stdout", "") + "\n" + result.get("stderr", "")
    counts: dict[str, int] = {}
    for label in ("passed", "failed", "error", "errors", "skipped"):
        matches = re.findall(rf"(\d+)\s+{label}\b", text)
        if matches:
            counts[label] = int(matches[-1])
    return counts


def _new_workspace(preferred: Path) -> Path:
    try:
        if preferred.exists():
            shutil.rmtree(preferred)
    except OSError:
        pass
    if preferred.exists():
        preferred = preferred.with_name(preferred.name + "-" + datetime.now(UTC).strftime("%H%M%S%f"))
    preferred.mkdir(parents=True)
    return preferred


def _check(results: list[dict[str, Any]], name: str, passed: bool, detail: str, evidence: Any = None) -> bool:
    results.append(
        {
            "name": name,
            "passed": bool(passed),
            "detail": detail,
            "evidence": evidence,
        }
    )
    return passed


def _context_identities(bundle: dict[str, Any]) -> tuple[set[str], set[str], set[str]]:
    specs = {item["symbol"] for item in bundle.get("specs", [])}
    code = {item["symbol"] for item in bundle.get("code", [])}
    tests = {item["symbol"] for item in bundle.get("tests", [])}
    return specs, code, tests


def generate_report(results: list[dict[str, Any]], *, run_id: str, extra: dict[str, Any]) -> dict[str, Any]:
    order = {
        "runnable": 0,
        "minimax_participation": 1,
        "context_correct": 2,
        "database_participation": 3,
        "state_reuse": 4,
        "code_change_effective": 5,
    }
    results = sorted(results, key=lambda item: (order.get(item["name"], 99), item["name"]))
    passed = sum(1 for item in results if item["passed"])
    report = {
        "run_id": run_id,
        "generated_at": now(),
        "passed": passed,
        "total": len(results),
        "all_passed": passed == len(results),
        "checks": results,
        **extra,
    }
    (VALIDATION / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [f"# MiniMax SDD 验证报告", "", f"- run_id: `{run_id}`", f"- 时间: {report['generated_at']}", f"- 结果: **{passed}/{len(results)}**", ""]
    lines.append("| 验收项 | 结果 | 证据 |")
    lines.append("| --- | --- | --- |")
    for item in results:
        lines.append(f"| {item['name']} | {'PASS' if item['passed'] else 'FAIL'} | {item['detail']} |")
    lines.append("")
    if extra.get("notes"):
        lines.append(extra["notes"])
        lines.append("")
    (VALIDATION / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-file", default=str(SAMPLE_TASK))
    parser.add_argument("--before-root", default=str(VALIDATION / "snapshots" / "before" / "demo_project"))
    parser.add_argument("--after-root", default=str(VALIDATION / "snapshots" / "after" / "demo_project"))
    parser.add_argument("--workspace", default=str(VALIDATION / "workspace"))
    parser.add_argument("--seekdb-dsn", default=None)
    parser.add_argument("--state-db", default=str(ROOT / ".runtime" / "powercontext-validation.db"))
    parser.add_argument("--use-minimax", action="store_true", help="capture a live MiniMax dev record")
    parser.add_argument("--minimax-record", default=str(RECORDS / "minimax_dev_record.jsonl"))
    args = parser.parse_args()

    RECORDS.mkdir(parents=True, exist_ok=True)
    VALIDATION.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    task = json.loads(Path(args.task_file).read_text(encoding="utf-8"))
    before_root = Path(args.before_root).resolve()
    after_root = Path(args.after_root).resolve()
    state_db = Path(args.state_db).resolve()
    if state_db.exists():
        state_db.unlink()

    # Clean per-run evidence logs (keep a previously captured MiniMax record).
    for log_name in ("db_query_record.jsonl", "powercontext_state_record.jsonl"):
        path = RECORDS / log_name
        if path.exists():
            path.unlink()

    workspace = _new_workspace(Path(args.workspace))
    project = workspace / "demo_project"
    shutil.copytree(before_root, project)
    logs_dir = VALIDATION / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    before_log = logs_dir / f"pytest-before-{run_id}.log"
    after_log = logs_dir / f"pytest-after-{run_id}.log"

    results: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    notes: list[str] = []

    store = SeekDBMaterialStore(dsn=args.seekdb_dsn, query_log=RECORDS / "db_query_record.jsonl")
    init_ok = False
    try:
        store.connect()
        store.reset()
        corpus = load_corpus(project)
        import_result = store.import_chunks(corpus)
        init_ok = True
        _check(
            results,
            "runnable",
            True,
            f"init imported {import_result['chunks']} chunks / {import_result['terms']} terms via {store.mode}",
            import_result,
        )
    except Exception as error:
        _check(results, "runnable", False, f"initialisation failed: {error}")
        report = generate_report(results, run_id=run_id, extra={"notes": "\n".join(notes)})
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    # ---- before tests -----------------------------------------------------
    before = run_before_after(project)
    before_log.write_text(
        "TARGET BEFORE\n" + json.dumps(before["target_before"], ensure_ascii=False, indent=2)
        + "\n\nREGRESSION BEFORE\n" + json.dumps(before["regression_before"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    target_before = before["target_before"]
    regression_before = before["regression_before"]
    target_counts = pytest_counts(target_before)
    regression_counts = pytest_counts(regression_before)
    before_ok = target_before["exit_code"] != 0 and regression_before["exit_code"] == 0
    diagnostics.append(
        {
            "name": "before_tests",
            "passed": before_ok,
            "detail": f"target exit={target_before['exit_code']} ({target_counts}); regression exit={regression_before['exit_code']} ({regression_counts})",
            "evidence": {"target": target_counts, "regression": regression_counts, "log": str(before_log)},
        }
    )

    # ---- state must be readable from a fresh process -----------------------
    save = run_cli(
        [
            "state-save",
            "--task-id", task["task_id"],
            "--status", "context_ready",
            "--completed", "task_defined",
            "--completed", "context_selected",
            "--todo", "implement_filters",
            "--todo", "run_target_tests",
            "--verification", json.dumps({"stage": "before", "target_failed": target_before["exit_code"] != 0}, ensure_ascii=False),
            "--notes", "Validation run: context selected before code change.",
        ],
        state_db=state_db,
    )
    context_json = workspace / "context_before.json"
    context_run = run_cli(
        [
            "context",
            "--task-id", task["task_id"],
            "--query", task["query"],
            "--project-root", str(project),
            "--json-out", str(context_json),
        ],
        state_db=state_db,
    )
    state_show = run_cli(["state-show", "--task-id", task["task_id"]], state_db=state_db)
    state_payload = {}
    try:
        state_payload = json.loads(state_show["stdout"]).get("state") or {}
    except ValueError:
        pass
    state_ok = (
        save["exit_code"] == 0
        and context_run["exit_code"] == 0
        and state_show["exit_code"] == 0
        and state_payload.get("status") == "context_ready"
        and "task_defined" in state_payload.get("completed", [])
        and state_payload.get("verification", {}).get("stage") == "before"
    )
    diagnostics.append(
        {
            "name": "state_reuse_initial",
            "passed": state_ok,
            "detail": f"state-show in a new process returned status={state_payload.get('status')}",
            "evidence": state_payload,
        }
    )

    # ---- context correctness ---------------------------------------------
    bundle_payload = json.loads(context_json.read_text(encoding="utf-8")) if context_json.exists() else {}
    specs, code_symbols, tests = _context_identities(bundle_payload)
    required = task["required"]
    missing_specs = [item for item in required["specs"] if item not in specs]
    missing_code = [item for item in required["code_symbols"] if item not in code_symbols]
    missing_tests = [item for item in required["tests"] if item not in tests]
    context_ok = not missing_specs and not missing_code and not missing_tests
    context_detail = {
        "missing_specs": missing_specs,
        "missing_code": missing_code,
        "missing_tests": missing_tests,
        "bundle": str(context_json),
    }

    # ---- spec update must flow through re-import --------------------------
    spec_project = workspace / "spec_update_project"
    shutil.copytree(project, spec_project)
    spec_file = spec_project / "specs" / "orders.md"
    original_spec = spec_file.read_text(encoding="utf-8")
    updated_spec = original_spec.replace(
        "- 传入未知状态时必须抛出 `ValueError`，不能静默返回空列表。",
        "- 传入未知状态时必须抛出 `ValueError`，不能静默返回空列表。\n- 更新（2026-11）：新增 `review` 状态，`review` 也必须按精确匹配返回。",
    )
    spec_file.write_text(updated_spec, encoding="utf-8", newline="\n")
    store.reset()
    store.import_chunks(load_corpus(spec_project))
    updated_bundle = select_context(
        store,
        task_id=task["task_id"],
        query="status review 状态筛选",
        project_root=spec_project,
    )
    updated_spec_text = "\n".join(item.excerpt for item in updated_bundle.specs if item.symbol == "SPEC-ORD-002")
    spec_update_ok = "review" in updated_spec_text and "更新（2026-11）" in updated_spec_text
    diagnostics.append(
        {
            "name": "spec_update_reimport",
            "passed": spec_update_ok,
            "detail": "SPEC-ORD-002 after re-import contains the new review clause" if spec_update_ok else "updated clause not present",
            "evidence": {"updated_spec_excerpt": updated_spec_text[:600]},
        }
    )
    # restore original index
    store.reset()
    store.import_chunks(load_corpus(project))

    # ---- apply candidate patch -------------------------------------------
    minimax_record_path = Path(args.minimax_record)
    minimax_patch_source = "reference"
    candidate_diff = (VALIDATION / "reference_change.patch").read_text(encoding="utf-8")

    if not args.use_minimax and minimax_record_path.exists():
        # Default reviewer path: replay the committed live MiniMax transcript.
        recorded = [json.loads(line) for line in minimax_record_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        for record in reversed(recorded):
            if record.get("provider") != "minimax":
                continue
            try:
                candidate_diff = extract_diff(str(record.get("response", {}).get("content", "")))
            except ValueError:
                continue
            (VALIDATION / "minimax_output.diff").write_text(candidate_diff, encoding="utf-8", newline="\n")
            minimax_patch_source = "recorded"
            notes.append("Replayed the committed MiniMax development record.")
            break

    if args.use_minimax and minimax_record_path.exists():
        # A live run should produce one fresh transcript, not append old attempts.
        minimax_record_path.unlink()
    if args.use_minimax and os.environ.get("MINIMAX_API_KEY"):
        capture = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "capture_minimax_dev_record.py"),
                "--context", str(context_json),
                "--before-root", str(project),
                "--record", str(minimax_record_path),
                "--output-diff", str(VALIDATION / "minimax_output.diff"),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            env=os.environ.copy(),
            timeout=600,
        )
        if capture.returncode == 0:
            candidate_diff = (VALIDATION / "minimax_output.diff").read_text(encoding="utf-8")
            minimax_patch_source = "live"
            notes.append("Candidate patch produced by a live MiniMax call.")
        else:
            notes.append(f"MiniMax capture failed: {capture.stderr[-500:]}")
            candidate_diff = (VALIDATION / "reference_change.patch").read_text(encoding="utf-8")
            minimax_patch_source = "reference"

    patch_result = apply_diff(project, candidate_diff, diff_path=workspace / "candidate.patch")

    # ---- after tests ------------------------------------------------------
    after = run_after_checks(project)
    after_log.write_text(
        "TARGET AFTER\n" + json.dumps(after["target_after"], ensure_ascii=False, indent=2)
        + "\n\nREGRESSION AFTER\n" + json.dumps(after["regression_after"], ensure_ascii=False, indent=2)
        + "\n\nFULL AFTER\n" + json.dumps(after["full_after"], ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    after_ok = (
        patch_result.applied
        and after["target_after"]["exit_code"] == 0
        and after["regression_after"]["exit_code"] == 0
        and after["full_after"]["exit_code"] == 0
    )
    diagnostics.append(
        {
            "name": "after_tests",
            "passed": after_ok,
            "detail": f"patch_applied={patch_result.applied}; target={pytest_counts(after['target_after'])}; regression={pytest_counts(after['regression_after'])}; full={pytest_counts(after['full_after'])}",
            "evidence": {
                "target": pytest_counts(after["target_after"]),
                "regression": pytest_counts(after["regression_after"]),
                "full": pytest_counts(after["full_after"]),
                "log": str(after_log),
                "candidate_provider": "minimax" if minimax_patch_source in ("live", "recorded") else "reference",
                "patch_source": minimax_patch_source,
            },
        }
    )

    # ---- final state revision --------------------------------------------
    final_verification = {
        "target_tests": pytest_counts(after["target_after"]),
        "regression_tests": pytest_counts(after["regression_after"]),
        "full_tests": pytest_counts(after["full_after"]),
        "patch_provider": "minimax" if minimax_patch_source in ("live", "recorded") else "reference",
    }
    final_save = run_cli(
        [
            "state-save",
            "--task-id", task["task_id"],
            "--status", "verified",
            "--completed", "code_modified",
            "--completed", "target_tests_passed",
            "--completed", "regression_tests_passed",
            "--clear-todo",
            "--verification", json.dumps(final_verification, ensure_ascii=False),
            "--notes", "Validation run complete.",
        ],
        state_db=state_db,
    )
    final_show = run_cli(["state-show", "--task-id", task["task_id"]], state_db=state_db)
    final_state = {}
    try:
        final_state = json.loads(final_show["stdout"]).get("state") or {}
    except ValueError:
        pass
    final_state_ok = (
        final_save["exit_code"] == 0
        and final_show["exit_code"] == 0
        and final_state.get("status") == "verified"
        and final_state.get("verification", {}).get("full_tests", {}).get("passed") == 11
    )
    diagnostics.append(
        {
            "name": "state_reuse_after_change",
            "passed": final_state_ok,
            "detail": f"final state status={final_state.get('status')}; verification={final_state.get('verification')}",
            "evidence": final_state,
        }
    )

    # ---- database participation ------------------------------------------
    stats = store.stats()
    db_log = RECORDS / "db_query_record.jsonl"
    db_records = db_log.read_text(encoding="utf-8").splitlines() if db_log.exists() else []
    db_ok = store.mode.startswith("seekdb-") and stats.get("chunks", {}).get("spec", 0) > 0 and len(db_records) > 0
    _check(results, "database_participation", db_ok, f"mode={store.mode}; chunks={stats.get('chunks')}; query_log_lines={len(db_records)}", stats)

    # ---- MiniMax participation -------------------------------------------
    minimax_ok = False
    minimax_evidence: dict[str, Any] = {"record": str(minimax_record_path), "exists": minimax_record_path.exists()}
    if minimax_record_path.exists():
        records = [json.loads(line) for line in minimax_record_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        minimax_records = [
            record
            for record in records
            if record.get("provider") == "minimax" and "minimax" in str(record.get("model", "")).lower()
        ]
        output_matches = True
        if minimax_patch_source in ("live", "recorded"):
            output_file = VALIDATION / "minimax_output.diff"
            output_matches = output_file.exists() and output_file.read_text(encoding="utf-8").strip() == candidate_diff.strip()
        minimax_ok = minimax_patch_source in ("live", "recorded") and bool(minimax_records) and patch_result.applied and output_matches
        minimax_evidence.update(
            {
                "records": len(records),
                "minimax_records": len(minimax_records),
                "models": [record.get("model") for record in minimax_records],
                "prompt_sha256": [record.get("prompt_sha256") for record in minimax_records],
                "output_matches_applied_patch": output_matches,
            }
        )
    _check(
        results,
        "minimax_participation",
        minimax_ok,
        "a MiniMax-provider transcript exists and its patch was applied" if minimax_ok else "no usable MiniMax transcript or its patch was not applied (run with a valid MINIMAX_API_KEY and --use-minimax)",
        minimax_evidence,
    )

    # ---- the remaining official gates ------------------------------------
    runnable_item = next(item for item in results if item["name"] == "runnable")
    runnable_ok = (
        init_ok
        and context_run["exit_code"] == 0
        and state_show["exit_code"] == 0
        and target_before["exit_code"] is not None
        and after["full_after"]["exit_code"] is not None
    )
    runnable_item["passed"] = runnable_ok
    runnable_item["detail"] = (
        f"init, context and validation sample executed via {store.mode}; "
        f"init_chunks={import_result['chunks']}, context_exit={context_run['exit_code']}, state_exit={state_show['exit_code']}"
    )
    _check(
        results,
        "context_correct",
        context_ok and spec_update_ok,
        f"required sources present; specs={sorted(specs)} code={sorted(code_symbols)} tests={len(tests)}; spec_update={spec_update_ok}",
        {**context_detail, "spec_update": spec_update_ok},
    )
    _check(
        results,
        "state_reuse",
        state_ok and final_state_ok,
        f"initial status={state_payload.get('status')}; final status={final_state.get('status')}",
        {"initial": state_payload, "final": final_state},
    )
    _check(
        results,
        "code_change_effective",
        before_ok and after_ok,
        f"before target={target_counts} regression={regression_counts}; after target={pytest_counts(after['target_after'])} regression={pytest_counts(after['regression_after'])} full={pytest_counts(after['full_after'])}",
        {"before": {"target": target_counts, "regression": regression_counts}, "after": next((item["evidence"] for item in diagnostics if item["name"] == "after_tests"), {})},
    )

    # ---- report -----------------------------------------------------------
    extra = {
        "run_id": run_id,
        "task": task,
        "workspace": str(workspace),
        "seekdb_mode": store.mode,
        "before": {"target": pytest_counts(target_before), "regression": pytest_counts(regression_before)},
        "after": {
            "target": pytest_counts(after["target_after"]),
            "regression": pytest_counts(after["regression_after"]),
            "full": pytest_counts(after["full_after"]),
        },
        "patch": str(workspace / "candidate.patch"),
        "minimax_record": str(minimax_record_path),
        "diagnostics": diagnostics,
        "notes": "\n".join(notes),
    }
    report = generate_report(results, run_id=run_id, extra=extra)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    store.close()
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
