# 验证材料说明

- `sample_task.json` / `sample_task.md`：验证样例的任务描述、必需来源、步骤与预期结果。
- `snapshots/before/demo_project`：修改前完整业务工程。
- `snapshots/after/demo_project`：修改后完整业务工程。
- `code_change.patch`：由修改前后快照生成的规范 unified diff。
- `minimax_output.diff`：真实 MiniMax 会话返回、并被验收重放的模型补丁。
- `expected_context.json`：上下文模块针对样例任务的实际输出。
- `report.json` / `report.md`：最近一次自动验收的六项结果、测试计数与证据路径。
- `logs/`：pytest 的完整命令、退出码、stdout/stderr。
- `fixtures/reference_change.diff`：仅用于离线自测的参考补丁包装，不是 MiniMax 记录。

一键验收：

```bash
cd minimax
python scripts/run_validation.py
```

默认 `python scripts/run_validation.py` 会重放已提交的真实 MiniMax 开发记录并得到 6/6；
配置 `MINIMAX_API_KEY` 后运行 `python scripts/run_validation.py --use-minimax`，
可以重新现场调用 MiniMax 并生成新的开发记录。
