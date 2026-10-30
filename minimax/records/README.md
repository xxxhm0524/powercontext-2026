# 技术使用记录

- `db_query_record.jsonl` / `.md`：每次上下文选择实际执行的 seekdb SQL、参数、返回行数与耗时。
- `powercontext_state_record.jsonl` / `.md`：PowerContext scope 创建、状态写入与跨进程读取。
- `minimax_dev_record.jsonl` / `.md`：MiniMax 开发会话的完整 prompt、响应、用量与延迟。

MiniMax 记录需要在配置 `MINIMAX_API_KEY` 后运行
`scripts/capture_minimax_dev_record.py` 生成。仓库不包含任何模型凭据。
