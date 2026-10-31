# 记忆酒馆（Memory Tavern）— Dify × PowerContext

> **一句话**：一个会记住你的角色扮演小酒馆。掌柜阿墨记得你的名字、你爱的酒、你欠下的账和上次没讲完的故事；下一次推门进来，他先叫出你的名字。

- Dify 应用名：**记忆酒馆**
- Dify 模式：**advanced-chat（Chatflow）**
- 指定技术：**PowerContext v1.2.0**（本题选择 PowerContext，未声明使用 seekdb）
- 提交目录：本 `dify/` 目录

---

## 1. 作品创意与玩法

### 1.1 故事设定

雾港的雨夜里有一家只在灯亮时营业的小酒馆。掌柜阿墨有一个怪癖：他不在乎客人付不付酒钱，却一定记得每一位客人的名字、口味和故事。你第一次推门时，他问你的名字；第二次推门时，他会把温好的酒推到你面前，说：“阿岚，桂花酿给你留着。上次你说要去雾港找一条船，后来呢？”

### 1.2 核心玩法循环

1. **推门**：用户在 Dify 聊天窗口输入第一句话，例如“我叫阿岚，是一名迷路的旅人，最喜欢桂花酿。”
2. **被记住**：Dify 调用 `POST /remember`，把**用户真实输入 + 阿墨的真实回应**写入 PowerContext 的长期 Memory。
3. **再见面**：用户结束当前对话，新建一个全新会话（Dify 同一 `sys.user_id`），问“还记得我吗？”
4. **记忆回响**：Dify 先调用 `POST /recall`，PowerContext 按当前问题做 FTS 检索并合并最近记忆；返回的“常客簿”被注入掌柜的 system prompt，阿墨于是能叫出名字、提起桂花酿和那枚铜币。
5. **继续生活**：每一轮都会形成新记忆。聊得越久，阿墨越像真的认识你。

### 1.3 为什么好玩

| 体验点 | 具体表现 |
| --- | --- |
| **被认出的瞬间** | 第二次会话第一句就是“阿岚，你回来了”，而不是通用欢迎语。 |
| **细节有回响** | 记得“桂花酿”“一枚铜币”“雾港找船”“小满”等用户随口说过的小事。 |
| **角色感** | 阿墨是温和、爱讲故事、偶尔俏皮的掌柜；回复有画面感，并会留一个钩子让对话继续。 |
| **可验证** | 后端 `/stats/{player_id}` 可以查看到底存了什么；`/recall` 返回的文本包含姓名和喜好，评审可以逐条核对，不是模型凭空编造。 |
| **多客隔离** | 每个 Dify 用户 `sys.user_id` 对应独立 PowerContext Scope，A 客人的记忆不会串到 B 客人。 |

### 1.4 推荐的体验样例

1. **第一次会话**：发送“我叫阿岚，是一名迷路的旅人，最喜欢桂花酿。身上只剩一枚铜币，先欠着酒钱吧。”
2. 继续聊：“给我讲讲雾港的故事吧，我想在那里找一条船。”
3. **新建对话**（同一 Dify 用户）：发送“掌柜的，还记得我吗？我叫什么名字？我最喜欢喝什么？”
4. 预期：阿墨先叫出“阿岚”，并自然提到“桂花酿”；可以顺带提到“一枚铜币”的欠账。

完整逐步验证、预期输出和实际运行记录见 [`validation.md`](validation.md)。

---

## 2. 技术分工

| 组件 | 在本作品中的职责 | 实际作用 |
| --- | --- | --- |
| **Dify（必选）** | 承担全部对话流程编排：接收输入 → HTTP 召回记忆 → LLM 角色扮演 → HTTP 写入记忆 → 回答。 | DSL 中可见 `开始 → 召回记忆 → 掌柜阿墨 → 记住这一轮 → 直接回复` 五个节点。 |
| **PowerContext（必选其一，本作品选择）** | 提供跨会话长期记忆：`/remember` 把每一轮真实对话写成 Memory 条目；`/recall` 按当前问题做 FTS 检索并合并近期记忆，返回给 Dify 作为提示词上下文。 | 后端通过官方公开 Runtime 接口 `open_builtin_runtime` 嵌入 PowerContext v1.2.0；数据落盘到 SQLite。不是 mock，也不是自制 JSON 记忆。 |
| seekdb | 本题未使用。 | 按题面“选择 PowerContext 的作品不额外要求使用 seekdb”。 |

### 2.1 一次对话的数据流

```text
用户输入
  │
  ▼
Dify 开始节点 (sys.user_id / sys.query)
  │
  ▼
HTTP POST /recall  ──────────────►  FastAPI 适配层
  │                                   │
  │                                   ├─ PowerContext Scope（按 player_id 隔离）
  │                                   ├─ memory.search(mode="fts", query=用户问题)
  │                                   └─ memory.list() 近期记忆
  │                                   ▼
  │                              返回“常客簿”纯文本
  ▼
LLM 掌柜阿墨（system prompt 注入常客簿 + Dify 会话窗口）
  │
  ▼
HTTP POST /remember ─────────────►  写入 PowerContext Memory
  │                                （用户原话 + 掌柜回复）
  ▼
回答节点（直接回复掌柜文本）
```

### 2.2 PowerContext 为什么是“真实接入”

- `backend/app.py` 直接 `from powercontext.builtin.runtime import open_builtin_runtime`，使用官方 v1.2.0 公开 API。
- `/remember` 调用 `memory.remember(RememberMemoryRequest(...))`，生成真实的 Memory Revision 和 `entry_id`。
- `/recall` 调用 `memory.search(SearchMemoryRequest(mode="fts"))` 和 `memory.list()`；召回文本被拼进 LLM system prompt。
- `/stats/{player_id}` 返回 PowerContext 里的 `scope_id`、`memory_count` 和最近条目，供评审核对。
- 重启后端后，同一个 `player_id` 会通过幂等 Scope 键回到原来的 Scope，记忆不会丢。

---

## 3. 文件清单

| 文件 | 用途 |
| --- | --- |
| `dsl/memory-tavern.yml` | 完整 Dify advanced-chat DSL；导入后即可看到五个节点及提示词。 |
| `backend/app.py` | FastAPI + PowerContext v1.2.0 适配层；`/recall`、`/remember`、`/stats/{player_id}`、`/health`。 |
| `backend/requirements.txt` | 后端依赖，PowerContext 固定到 v1.2.0 提交 `9db1753434162c0aa7c9f1189a1722e617880a52`。 |
| `backend/smoke_test.py` | 无需 Dify 的端到端冒烟测试：首次见面、写入、召回、用户隔离、重启恢复、表单特殊字符。 |
| `tools/validate_dsl.py` | DSL 静态检查：节点链、变量引用、form-data 字段、无密钥。 |
| `validation.md` | 可逐步执行的验证样例、预期表现、实际运行记录与证据索引。 |
| `evidence/` | 后端实际运行日志、HTTP 请求记录、数据库核对记录（如已生成）。 |
| `README.md` | 本运行说明。 |

---

## 4. 运行环境

| 项 | 要求 |
| --- | --- |
| Dify | 社区版 / 自托管，建议 **0.15 及以上**（DSL `version: 0.1.5`，已在 Dify 0.15.3 上实测导入与运行）。Dify Cloud 也可导入，按页面提示升级即可。 |
| Python | 3.11 / 3.12 / 3.13（推荐 3.12；本机验证使用 3.13）。 |
| 操作系统 | Windows / Linux / macOS。 |
| PowerContext | `powercontext[builtin]`，固定 v1.2.0 提交 `9db1753434162c0aa7c9f1189a1722e617880a52`。 |
| 模型 | 任意可用 Chat 模型；DSL 默认占位 `openai / gpt-4o-mini`，导入后按第 5.3 节重新绑定。 |
| Embedding / Rerank | **不需要**；召回使用 SQLite FTS，不依赖在线 Embedding 或 Rerank 服务。 |
| 资源 | 后端常驻内存约 100–200 MB；Dify 侧按官方最低要求即可。 |

---

## 5. 快速开始

### 5.1 启动 PowerContext 记忆后端

```bash
cd dify/backend

# 创建虚拟环境（Windows 与 macOS/Linux 通用）
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
# source .venv/bin/activate

pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8099
```

首次启动会创建 `backend/data/memory_tavern.db`。看到类似日志即表示就绪：

```text
INFO memory_tavern memory tavern ready: database=...\data\memory_tavern.db
INFO:     Uvicorn running on http://0.0.0.0:8099
```

另开一个终端验证：

```bash
curl http://127.0.0.1:8099/health
# {"status":"ok","powercontext":"ready","database":"...memory_tavern.db"}
```

> 如果 `pip install -r requirements.txt` 拉取 GitHub 超时，可先 `git clone https://github.com/oceanbase/powercontext.git` 并 `git checkout 9db17534`，然后执行 `pip install fastapi uvicorn httpx python-multipart && pip install -e /path/to/powercontext[builtin]`。详见第 10 节。

### 5.2 导入 Dify DSL

1. 打开 Dify → **工作室** → **创建应用** → **导入 DSL 文件**。
2. 选择 `dsl/memory-tavern.yml`。
3. 导入后进入应用，打开 **掌柜阿墨** LLM 节点，在模型下拉框中重新选择你自己的 Chat 模型与 provider（默认 `openai / gpt-4o-mini` 只是占位，不需要 OpenAI Key 也能先看流程）。
4. 检查两个 HTTP 请求节点的地址，按你的部署方式选择：

| Dify 部署方式 | `/recall` 与 `/remember` 的 URL |
| --- | --- |
| Dify 用 Docker 本地部署（推荐） | `http://host.docker.internal:8099/recall`、`http://host.docker.internal:8099/remember`（DSL 默认值） |
| Dify 与后端在同一台机器、直接运行 | `http://127.0.0.1:8099/recall`、`http://127.0.0.1:8099/remember` |
| Dify 云端版 | 把后端部署到公网可访问的 HTTPS 地址，例如 `https://your-host.example.com/recall`；不要填 `localhost` |
| Dify 与后端都在同一 Docker 网络 | 使用后端容器名，例如 `http://memory-tavern:8099/recall` |

5. 保存并 **发布** 应用，打开聊天窗口开始体验。

> DSL 中的 HTTP 节点使用 **form-data** 传参，而不是把用户输入直接拼进 JSON 字符串。这样用户输入引号、换行或表情时不会破坏请求体。后端同时兼容 `application/json`、`multipart/form-data` 和 `application/x-www-form-urlencoded`。

### 5.3 重新绑定模型（必须）

DSL 里的 `openai / gpt-4o-mini` 是占位配置：

1. 打开「掌柜阿墨」LLM 节点；
2. 在模型选择器中选你已配置好的 provider 和模型（OpenAI、Azure OpenAI、OpenAI-API-compatible、通义、DeepSeek 等均可）；
3. 建议 `temperature` 保持 0.7–0.9，其他参数默认；
4. 保存并发布。

只要模型支持中文对话即可，不要求 Embedding 或 Rerank。

### 5.4 应用入口

- Dify Studio 内打开「记忆酒馆」→ 聊天窗口；
- 或通过 Dify 的「访问 API」页面调用 `POST /chat-messages`，`user` 字段对应本作品的 `player_id` / `sys.user_id`。同一 `user` 值跨会话共享记忆。

---

## 6. 验证

### 6.1 后端冒烟测试（不需要 Dify）

```bash
cd dify/backend
python smoke_test.py
```

预期最后一行：

```text
SMOKE TEST PASSED
```

该测试会使用真实的 PowerContext Runtime（SQLite 持久化）完整走通：空记忆兜底 → 写入两轮 → 召回姓名/喜好 → 第二个用户隔离 → 重启后仍能召回 → 引号与换行表单输入。

### 6.2 Dify 两轮会话验证

按 [`validation.md`](validation.md) 的「样例 A / 样例 B」执行。核心检查点：

- 第一次会话后，后端日志出现一条 `remember player=...`；
- 新建对话后，后端日志出现一条 `recall player=...`，且返回文本包含“阿岚”“桂花酿”；
- Dify 的「召回记忆」节点执行记录中能看到 HTTP 200 和返回的常客簿文本；
- `curl http://127.0.0.1:8099/stats/<player_id>` 能看到 `memory_count >= 2` 与最近条目。

### 6.3 运行证据

`evidence/` 目录保存了本仓库交付前的真实运行输出（详见 `validation.md` 第六节）：

- `dify_e2e.md`：**真实 Dify 0.15.3 端到端记录**——DSL 导入 `completed`、工作流发布、两次独立会话回答、五个节点执行摘要；
- `dify_import.json` / `dify_import_submitted.json` / `dify_chat_transcript.json` / `dify_workflow_db.txt` / `dify_node_outputs.json`：Dify 导入结果、会话正文、工作流数据库记录与召回/写入节点原文；
- `backend_smoke.log`：完整冒烟测试日志；
- `http_api.md`：独立启动 uvicorn 后的 HTTP 请求/响应记录；
- `http_restart.md`：后端重启后的记忆恢复记录；
- `stats.json` / `powercontext_sqlite.md`：PowerContext 实际存储与 SQLite 核对；
- `dsl_check.txt`：DSL 静态检查结果。

---

## 7. 数据、状态与恢复

| 项 | 说明 |
| --- | --- |
| 数据目录 | 默认 `backend/data/`，数据库文件 `memory_tavern.db`。 |
| 自定义目录 | 设置环境变量 `MEMORY_TAVERN_DATA=/path/to/data`。 |
| 召回条数 | `MEMORY_TAVERN_RECALL_LIMIT`，默认 12。 |
| 单条截断 | `MEMORY_TAVERN_ENTRY_CHARS`，默认 800 字符。 |
| 上下文总预算 | `MEMORY_TAVERN_CONTEXT_CHARS`，默认 6000 字符。 |
| 重置全部记忆 | 停止后端，删除 `backend/data/memory_tavern.db`，重启。 |
| 只重置一个玩家 | 换一个新的 `player_id`（Dify 用户身份）即可；旧 Scope 保留。 |
| 查看某玩家记忆 | `GET /stats/{player_id}`。 |

PowerContext Scope 使用 `memory-tavern:<sha256(player_id)>` 作为幂等键，因此后端重启后会复用原 Scope，不会把同一用户拆成多个记忆空间。

---

## 8. 设计与实现说明

### 8.1 召回策略

1. **FTS 检索**：以用户当前问题调用 PowerContext `memory.search(mode="fts")`，利用其 Analyzer v1 对中文的 unigram/bigram 切分，召回相关旧事。
2. **近期记忆补齐**：再调用 `memory.list()`，按时间倒序补齐 FTS 未覆盖的近期对话，保证“上次刚说过”的事一定在场。
3. **常客簿提取**：从真实记忆中提取姓名、最爱的酒等稳定事实，放在提示词最前面，降低模型忽略细节的概率；提取不到时不编造。
4. **预算控制**：单条 800 字、总量 6000 字上限，避免历史无限增长撑爆模型上下文。

### 8.2 写入策略

- 每轮保存一条 `episode`：`玩家说：<用户原话>\n掌柜回应：<模型回复>`。
- 保存的是**用户真实输入**和**模型真实输出**，不是固定示例文本。
- 写入失败不会伪造成功；HTTP 节点启用重试（2 次，间隔 150ms），后端返回明确的 `entry_id` 供核对。

### 8.3 异常处理

| 场景 | 行为 |
| --- | --- |
| 后端未启动 / 网络不通 | Dify HTTP 节点显示错误并重试；README 第 10 节给出排查表。 |
| PowerContext 尚未初始化 | `/health` 返回 503/启动失败；等待 lifespan 完成后再请求。 |
| 用户输入超长 | Pydantic 返回 422 和字段错误，不会写入半条记忆。 |
| 用户输入包含引号/换行 | Dify form-data 原样传输，后端完整保存。 |
| 空记忆 | `/recall` 返回“第一次见面”的兜底话术，LLM 按第一次接待。 |
| 重启 | Scope 幂等键保证记忆继续可用。 |

### 8.4 安全与隐私

- 不包含任何真实 API Key、密码或令牌；Dify 模型凭据由评审自行配置。
- 后端只暴露本地记忆接口，默认监听 `0.0.0.0:8099`；公网部署时请自行加反向代理、鉴权和 HTTPS。
- `/stats/{player_id}` 仅用于本地验证；公网部署建议关闭或加鉴权。

---

## 9. 已知限制

1. 当前按“整轮对话”保存记忆，不做结构化事实抽取；常客簿中的姓名/酒名是轻量规则提取，主要用于提高提示词可读性，完整事实仍在原始记忆中。
2. 召回质量依赖 SQLite FTS；对同义改写（例如“最爱喝的”与“桂花酿”）主要依靠近期记忆补齐和模型理解，不是向量语义检索。
3. 作品按单机 Demo 设计；并发量、鉴权、多租户配额不在本题范围内。
4. Dify Cloud 无法访问 `localhost`，必须把后端部署到公网 HTTPS 地址（见 5.2 表）。
5. 模型回复质量取决于评审绑定的 Chat 模型；本作品不绑定特定模型供应商。

---

## 10. 故障排查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| Dify 节点报 `Connection refused` / `host.docker.internal` 解析失败 | Dify 容器网络无法访问宿主机 | 改用 `http://172.17.0.1:8099`（Linux Docker）或把后端部署到同一网络；确认后端 `--host 0.0.0.0`。 |
| Dify 云端报 `localhost` 不可达 | 云端无法访问你的本机 | 使用公网 HTTPS 地址或临时隧道（ngrok/cloudflared），并把 URL 填进两个 HTTP 节点。 |
| `pip install` 卡在 GitHub | 网络无法 clone PowerContext | 先手动 clone 并 checkout `9db17534`，再 `pip install -e /path/to/powercontext[builtin]`。 |
| 启动报 `ModuleNotFoundError: powercontext` | 没装依赖或虚拟环境未激活 | 确认 `pip show powercontext` 显示 1.2.0，且使用同一 Python。 |
| `/recall` 总是“第一次见面” | `player_id` 变了（换了浏览器/用户） | Dify Web 端同一浏览器用户一致；调试时直接用 `curl` 指定固定 `player_id`。 |
| 模型回答不提记忆 | 模型节点未绑定或提示词被覆盖 | 检查 LLM 节点 system prompt 中是否有 `{{#1800000000002.body#}}`；重新绑定模型。 |
| 中文召回不稳定 | FTS 对极短查询可能只命中少量 bigram | 在问题中包含一个具体线索（名字、酒名、地点）；或提高 `MEMORY_TAVERN_RECALL_LIMIT`。 |

---

## 11. 按题面验收的自查表

| 题面要求 | 本作品对应材料 | 状态 |
| --- | --- | --- |
| Dify DSL 可导入、可运行 | `dsl/memory-tavern.yml`，五节点完整链路 | ✅ |
| 至少一组完整验证样例 | `validation.md` 样例 A/B，含初始状态、输入、步骤、预期 | ✅ |
| 技术结合有效：Dify 核心编排 | DSL 中开始/HTTP/LLM/HTTP/回答五节点，HTTP 节点真实调用后端 | ✅ |
| PowerContext 实际保存并复用记忆 | `backend/app.py` 调用官方 Runtime；`/stats` 可查真实条目；跨会话样例 | ✅ |
| 过程可复现、不依赖作者本地状态 | `requirements.txt` 固定版本、启动命令、数据目录、重置方法、冒烟测试 | ✅ |
| 运行说明覆盖环境/模型/网络/限制 | 本文第 4、5、9、10 节 | ✅ |
| 不提交真实密钥 | DSL 与后端无任何 Key；模型由评审绑定 | ✅ |
| 复用来源与改动说明 | 第 12 节 | ✅ |

---

## 12. 来源与改动

- **PowerContext**：使用 `oceanbase/powercontext` 标签 `powercontext-v1.2.0`，提交 `9db1753434162c0aa7c9f1189a1722e617880a52`。后端只调用其公开 Runtime 接口，未修改其源码。
- **Dify DSL**：参考公开示例仓库 `dzh-gitcode/dify-workflows` 的节点组织方式，按本作品流程重新编写；未复用其中业务逻辑、提示词或密钥。
- **对话与验证数据**：全部为本项目自造（阿岚、雾港、桂花酿、铜币、小满等），不包含真实个人信息。
- **模型**：DSL 默认占位 `openai / gpt-4o-mini`；评审需绑定自己的模型，作品不附带任何模型凭据。

---

## 13. 30 秒评审速查

```bash
# 1. 起后端
cd dify/backend && pip install -r requirements.txt && uvicorn app:app --port 8099

# 2. 健康检查
curl http://127.0.0.1:8099/health

# 3. 无需 Dify 的完整记忆链路
python smoke_test.py

# 4. 导入 dify/dsl/memory-tavern.yml，绑定模型，按 validation.md 聊两轮

# 5. 看真实存了什么
curl http://127.0.0.1:8099/stats/<你的 Dify 用户 ID>
```
