# 验证样例与运行证据

本文件给出可直接按步骤复现的验证样例。作品的核心能力是「跨会话记住玩家」，因此用两个独立会话验证；另附后端冒烟测试、HTTP 记录和 PowerContext 数据库核对。

---

## 一、准备

1. 按 `README.md` 启动后端：

   ```bash
   cd dify/backend
   pip install -r requirements.txt
   uvicorn app:app --host 0.0.0.0 --port 8099
   ```

2. 在 Dify 中导入 `dsl/memory-tavern.yml`，绑定一个可用的 Chat 模型。
3. 使用**同一个 Dify 用户身份**（`sys.user_id` 固定）进行两个会话。Dify 的「新建对话」按钮即可产生新会话，但用户身份不变。
4. 初始状态：全新用户，`backend/data/memory_tavern.db` 中没有该用户的 Memory。如果想确保从零开始，使用一个新的 Dify 用户或删除数据库后重启。

---

## 二、样例 A：建立记忆（第一次会话）

**初始状态**：全新用户，`backend/data/memory_tavern.db` 中没有该用户的 Memory。

**输入 1**：

> 我叫阿岚，是一名迷路的旅人，最喜欢桂花酿。身上只剩一枚铜币，先欠着酒钱吧。

**预期表现**：

- 阿墨以酒馆掌柜口吻回应，称呼「阿岚」。
- 会提到桂花酿或那枚铜币，语言自然，不出现「记忆库/系统/数据」等词。
- 回复 2～4 句，并以一个轻松的问题收尾。

**后端记录**：Dify 的「记住这一轮」节点调用 `POST /remember`，返回类似：

```json
{"status":"saved","entry_id":"mem_ent_9d3ef40985e44434932a26db34a92622","memory_artifact_id":"memory"}
```

**输入 2**（同一会话继续）：

> 给我讲讲雾港的故事吧，我想在那里找一条船。

**预期表现**：阿墨讲一个具体的雾港小故事，并在结尾把话题抛回给阿岚（例如问她要去哪里）。

---

## 三、样例 B：跨会话召回（第二次会话）

**初始状态**：点击「新建对话」，同一 Dify 用户；后端数据库保留上一节写入的 Memory。

**输入**：

> 掌柜的，还记得我吗？我叫什么名字？我最喜欢喝什么？

**预期表现**：

- 阿墨应当先叫出「阿岚」。
- 应当提到「桂花酿」。
- 可以顺带提到「一枚铜币」的欠账（属于加分表现，允许因召回数量上限而不出现）。

**技术核对**：

- Dify 的「召回记忆」节点调用 `POST /recall`，后端返回的纯文本中包含 `阿岚` 与 `桂花酿`。
- 该文本被拼进 LLM system prompt（DSL 中的 `{{#1800000000002.body#}}`），因此回答有据可查，不是模型自由发挥。
- 打开 Dify 的节点执行详情，可看到「召回记忆」HTTP 200、响应体即下方「实际运行结果」。

**实际运行结果（后端侧，来自本仓库 `evidence/http_api.md`）**：

```text
【常客簿】
姓名：阿岚
最爱的酒：桂花酿

【记忆片段】
- 玩家说：我叫阿岚，是一名迷路的旅人，最喜欢桂花酿。身上只剩一枚铜币，先欠着酒钱吧。
掌柜回应：阿岚，桂花酿给你留着，铜币的事我也记着。
- 玩家说：给我讲讲雾港的故事吧，我想在那里找一条船。
掌柜回应：雾港的船都藏在雾里，等风停了才肯露面。
```

---

## 四、样例 C：用户隔离与重启恢复

### C1. 用户隔离

用另一个 `player_id`（或在另一个浏览器身份下打开 Dify）发送：

> 我叫什么名字？

**实际结果**：

```text
【常客簿】还是空的。这是你们第一次见面。
请热情地招呼这位旅人，问问他的名字，再问他想喝点什么。
```

说明不同用户之间的 PowerContext Scope 完全隔离。

### C2. 后端重启恢复

1. 停止后端；
2. 用同一个 `MEMORY_TAVERN_DATA` 目录重新启动；
3. 用原 `player_id` 再次调用 `/recall`。

**实际结果**（`evidence/http_restart.md`）：

```text
【常客簿】
姓名：阿岚
最爱的酒：桂花酿

【记忆片段】
- 玩家说：我叫阿岚，是一名迷路的旅人，最喜欢桂花酿。身上只剩一枚铜币，先欠着酒钱吧。
掌柜回应：阿岚，桂花酿给你留着，铜币的事我也记着。
- 玩家说：给我讲讲雾港的故事吧，我想在那里找一条船。
掌柜回应：雾港的船都藏在雾里，等风停了才肯露面。
```

`/stats/dify-demo-user` 返回的 `scope_id` 在重启前后一致，`memory_count` 仍为 2，证明 Scope 幂等复用而非新建空空间。

---

## 五、后端冒烟测试（无需 Dify）

在 `backend/` 目录执行：

```bash
python smoke_test.py
```

预期输出（节选）：

```text
【常客簿】
姓名：阿岚
最爱的酒：桂花酿

【记忆片段】
- 玩家说：我叫阿岚，是一名迷路的旅人，最喜欢桂花酿。身上只剩一枚铜币，先欠着酒钱吧。
掌柜回应：阿岚，桂花酿给你留着，铜币的事我也记着。

SMOKE TEST PASSED
```

该测试使用真实的 PowerContext `open_builtin_runtime`（SQLite 持久化），完整覆盖：

- 空记忆兜底；
- `/remember` 写入两轮真实对话；
- `/recall` 召回姓名/喜好；
- 第二个用户隔离；
- 后端 lifespan 重启后记忆仍在；
- `multipart/form-data` 表单中的引号、换行、特殊字符；
- `/stats` 条目数核对。

---

## 六、实际运行环境与证据索引

**本机实测环境**：

| 项 | 值 |
| --- | --- |
| 操作系统 | Windows 11 (10.0.26200) |
| Python | 3.13.12（后端）/ 3.11（Dify） |
| Dify | 0.15.3 社区版源码，Flask API 端口 5001；DSL `version: 0.1.5` 导入状态 `completed` |
| PowerContext | 1.2.0，提交 `9db1753434162c0aa7c9f1189a1722e617880a52` |
| FastAPI / Uvicorn | fastapi 0.162.0 / uvicorn 0.54.0 |
| 后端启动方式 | `uvicorn app:app --host 127.0.0.1 --port 8099` |

**证据文件**：

| 文件 | 内容 |
| --- | --- |
| `evidence/dify_e2e.md` | **真实 Dify 0.15.3 端到端记录**：DSL 导入 `completed`、工作流发布、两次独立会话的回答、节点执行摘要。 |
| `evidence/dify_import_submitted.json` | **提交版 DSL**（`dsl/memory-tavern.yml` 原文件）的导入返回：`status: completed`，DSL 0.1.5。 |
| `evidence/dify_import.json` | 本机端到端验证所用副本（仅把 URL 改为 `127.0.0.1`）的导入返回。 |
| `evidence/dify_chat_transcript.json` | 两次会话的 `conversation_id` 与回答正文。 |
| `evidence/dify_workflow_db.txt` | Dify PostgreSQL 中 `workflow_runs` / `workflow_node_executions` 的查询结果，五个节点全部 `succeeded`。 |
| `evidence/dify_node_outputs.json` | 「召回记忆」节点完整返回（常客簿正文）与「记住这一轮」节点完整返回（真实 `entry_id`）。 |
| `evidence/backend_smoke.log` | `python smoke_test.py` 的完整控制台输出，末行 `SMOKE TEST PASSED`。 |
| `evidence/http_api.md` | 独立启动 uvicorn 后的 9 组真实 HTTP 请求/响应（健康检查、首次召回、两次写入、跨会话召回、stats、隔离、422 校验、JSON 兼容）。 |
| `evidence/http_restart.md` | 停止并重启后端后的记忆恢复记录；`scope_id` 不变。 |
| `evidence/stats.json` | `/stats/dify-demo-user` 的真实 JSON 返回，含 `scope_id`、`memory_count`、最近条目。 |
| `evidence/powercontext_sqlite.md` | 直接查询 PowerContext SQLite 的表行数与真实 Memory 文本。 |
| `evidence/dsl_check.txt` | `tools/validate_dsl.py` 的静态检查结果：节点链、变量引用、form-data 字段、无密钥。 |
| `evidence/uvicorn.log` / `evidence/uvicorn_restart.log` | 两次后端启动日志，含 `memory tavern ready` 与请求日志。 |

**Dify 实测结论**：本仓库已在真实 Dify 0.15.3 上完成 DSL 导入（`status: completed`）、工作流发布和两次独立会话。第二次会话的 `conversation_id` 与第一次不同，但回答仍包含「阿岚」「桂花酿」；Dify 数据库记录显示五个节点全部 `succeeded`，其中「召回记忆」节点 `status_code: 200` 且 body 为常客簿，「记住这一轮」节点返回真实 `entry_id`。完整记录见 [`evidence/dify_e2e.md`](evidence/dify_e2e.md)。

> 本机验收时 LLM 节点指向一个本地 OpenAI 兼容桩模型，以保证无外部模型 Key 时也能确定性地核对流程；Dify、HTTP 节点、FastAPI 后端与 PowerContext 均为真实组件。评审按 README 绑定自己的 Chat 模型即可。

**Dify 侧核对点**（评审导入 DSL 后）：

1. 打开「召回记忆」节点执行详情：HTTP 200，响应体包含「常客簿」；
2. 打开「记住这一轮」节点执行详情：HTTP 200，响应体含 `"status":"saved"` 与 `entry_id`；
3. 新建对话后再次发送问题：回答中出现「阿岚」「桂花酿」；
4. `GET /stats/<Dify 用户 ID>` 的 `memory_count` 随对话轮数增长。

---

## 七、恢复初始状态

- **清空全部记忆**：停止后端，删除 `backend/data/memory_tavern.db`（以及同目录 `-wal`/`-shm` 文件），重启。
- **只换一个玩家**：在 Dify 中使用新的用户身份，或直接用新 `player_id` 调用后端接口。
- **保留旧数据但想重看第一次见面**：换 `player_id` 即可；旧 Scope 不会被删除。

---

## 八、失败排查

| 现象 | 排查 |
| --- | --- |
| `/health` 不通 | 确认 uvicorn 已启动、端口 8099 未被占用、`--host 0.0.0.0`。 |
| Dify 报 `Connection refused` | 容器内不能用 `127.0.0.1` 访问宿主机；改用 `host.docker.internal`、`172.17.0.1` 或同一 Docker 网络的服务名。 |
| Dify Cloud 报 `localhost` 不可达 | 用公网 HTTPS 地址或临时隧道，并替换两个 HTTP 节点的 URL。 |
| 每次都是「第一次见面」 | 检查两次会话的 `sys.user_id` 是否一致；换浏览器/隐身窗口会换用户。 |
| `/recall` 返回 422 | 检查 form-data 字段名是否为 `player_id`、`query`；`/remember` 为 `player_id`、`user_message`、`assistant_reply`。 |
| 回答不提记忆 | 检查 LLM system prompt 中是否保留 `{{#1800000000002.body#}}`；确认「召回记忆」节点在 LLM 之前执行。 |
