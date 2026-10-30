"""Turn JSONL evidence logs into human-readable submission records."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORDS = ROOT / "records"


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def db_record() -> str:
    rows = read_jsonl(RECORDS / "db_query_record.jsonl")
    lines = ["# seekdb 查询与索引使用记录", ""]
    if not rows:
        lines.append("（暂无记录；运行 `python scripts/run_validation.py` 生成。）")
        return "\n".join(lines) + "\n"
    lines.append(f"- 查询次数：{len(rows)}")
    lines.append(f"- 数据库模式：`{rows[0].get('mode', '')}`")
    lines.append("")
    lines.append("| 时间 | 操作 | 参数 | 返回行数 | 耗时 (ms) |")
    lines.append("| --- | --- | --- | --- | --- |")
    for row in rows:
        params = json.dumps(row.get("params"), ensure_ascii=False)
        if len(params) > 120:
            params = params[:117] + "..."
        lines.append(
            f"| {row.get('timestamp', '')} | {row.get('operation', '')} | `{params}` | {row.get('row_count', '')} | {row.get('elapsed_ms', '')} |"
        )
    lines.append("")
    lines.append("## 完整 SQL（最近一次）")
    lines.append("")
    lines.append("```sql")
    lines.append(rows[-1].get("sql", ""))
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def state_record() -> str:
    rows = read_jsonl(RECORDS / "powercontext_state_record.jsonl")
    lines = ["# PowerContext 状态写入与复用记录", ""]
    if not rows:
        lines.append("（暂无记录；运行 `python scripts/run_validation.py` 生成。）")
        return "\n".join(lines) + "\n"
    lines.append(f"- 操作次数：{len(rows)}")
    lines.append(f"- PowerContext SQLite：`{rows[0].get('db', '')}`")
    lines.append("")
    lines.append("| 时间 | 动作 | scope | entry | task | status |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for row in rows:
        lines.append(
            f"| {row.get('timestamp', '')} | {row.get('action', '')} | `{row.get('scope_id', '')}` | "
            f"`{row.get('entry_id', '')}` | {row.get('task_id', '')} | {row.get('status', '')} |"
        )
    lines.append("")
    lines.append("说明：`save` 是写入，`load_hit` 是另一个进程中的重启读取；两次 `state-show` 均由独立 CLI 进程执行。")
    lines.append("")
    return "\n".join(lines)


def minimax_record() -> str:
    path = RECORDS / "minimax_dev_record.jsonl"
    rows = read_jsonl(path)
    lines = ["# MiniMax 开发记录", ""]
    if not rows:
        lines.append("（尚未捕获真实 MiniMax 会话。设置 `MINIMAX_API_KEY` 后运行：")
        lines.append("")
        lines.append("```bash")
        lines.append("python scripts/capture_minimax_dev_record.py \\")
        lines.append("  --context validation/expected_context.json \\")
        lines.append("  --before-root validation/snapshots/before/demo_project")
        lines.append("```")
        lines.append("")
        lines.append("然后重新运行 `python scripts/run_validation.py --use-minimax`。）")
        return "\n".join(lines) + "\n"
    lines.append(f"- 会话条数：{len(rows)}")
    for index, row in enumerate(rows, start=1):
        lines.append("")
        lines.append(f"## 会话 {index}")
        lines.append(f"- 时间：{row.get('timestamp', '')}")
        lines.append(f"- 提供方：{row.get('provider', '')}")
        lines.append(f"- 模型：{row.get('model', '')}")
        lines.append(f"- API 风格：{row.get('api_style', '')}")
        lines.append(f"- 延迟：{row.get('latency_ms', '')} ms")
        lines.append(f"- prompt sha256：`{row.get('prompt_sha256', '')}`")
        lines.append("")
        lines.append("### 提供的上下文（prompt 摘要）")
        request = row.get("request", {})
        message_text = "\n".join(item.get("content", "") for item in request.get("messages", []))
        lines.append("```text")
        lines.append(message_text[:4000])
        lines.append("```")
        lines.append("")
        lines.append("### 模型返回")
        lines.append("```text")
        lines.append(str(row.get("response", {}).get("content", ""))[:12000])
        lines.append("```")
    return "\n".join(lines) + "\n"


def main() -> int:
    RECORDS.mkdir(parents=True, exist_ok=True)
    (RECORDS / "db_query_record.md").write_text(db_record(), encoding="utf-8")
    (RECORDS / "powercontext_state_record.md").write_text(state_record(), encoding="utf-8")
    (RECORDS / "minimax_dev_record.md").write_text(minimax_record(), encoding="utf-8")
    print("records rebuilt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
