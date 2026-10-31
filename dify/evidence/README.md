# 运行证据索引

本目录保存交付前的真实验证输出。所有记录都可在 `validation.md` 描述的步骤下重新生成。

| 文件 | 来源/命令 | 内容 |
| --- | --- | --- |
| `dify_e2e.md` | 真实 Dify 0.15.3 + 后端 | DSL 导入、工作流发布、两次独立会话、节点执行摘要 |
| `dify_import_submitted.json` | `POST /console/api/apps/imports`（提交版 DSL） | 导入结果 `status: completed` |
| `dify_import.json` | `POST /console/api/apps/imports`（本机 URL 副本） | 导入结果 `status: completed` |
| `dify_chat_transcript.json` | `POST /v1/chat-messages` | 两次会话的 `conversation_id` 与回答 |
| `dify_workflow_db.txt` | Dify PostgreSQL | `workflow_runs` / `workflow_node_executions`，五个节点全部 succeeded |
| `dify_node_outputs.json` | Dify PostgreSQL | 「召回记忆」返回的常客簿原文、「记住这一轮」返回的真实 `entry_id` |
| `dify-e2e-stats.json` | `GET /stats/dify-e2e-user` | Dify 端到端用户的实际记忆数与最近条目 |
| `backend_smoke.log` | `python backend/smoke_test.py` | 空记忆兜底、写入、召回、隔离、重启、表单特殊字符 |
| `http_api.md` | 独立 uvicorn + HTTP 请求 | 9 组真实 HTTP 请求/响应 |
| `http_restart.md` | 停止/重启后端 | 同一 Scope 的记忆恢复记录 |
| `stats.json` | `GET /stats/dify-demo-user` | PowerContext 条目数、scope_id、最近条目 |
| `powercontext_sqlite.md` | SQLite 查询 | 表行数与真实 Memory 文本 |
| `dsl_check.txt` | `python tools/validate_dsl.py` | 节点链、变量引用、form-data 字段、无密钥检查 |
| `uvicorn.log` / `uvicorn_restart.log` | uvicorn | 后端启动与请求日志 |

> `dify_e2e.md` 中的 LLM 回复来自一个本地 OpenAI 兼容桩模型，仅用于在没有外部模型 Key 的机器上确定性地验证 Dify 工作流；Dify、HTTP 节点、FastAPI 后端与 PowerContext 均为真实运行。评审按 README 第 5.3 节绑定自己的模型即可获得真实角色回复。
