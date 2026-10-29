# 记忆酒馆（Memory Tavern）— Dify × PowerContext

> Just for Fun：一个会记住你的角色扮演小酒馆。掌柜阿墨会记住你的名字、喜好、约定和上次讲的故事；下一次推门进来，他还认得你。

## 1. 作品是什么

「记忆酒馆」是一个基于 Dify Chatflow 的轻量互动叙事应用。用户扮演一位旅人走进酒馆，和掌柜阿墨聊天。每一轮对话结束后，应用会把这一轮内容写入 PowerContext 的长期 Memory；下一轮（以及下一次全新会话）开始时，应用先从 PowerContext 召回该用户的历史记忆，再交给大模型生成符合角色设定的回应。

**好玩的点：**

- 第一次见面，阿墨会问你的名字；第二次见面，他会先叫出你的名字。
- 你说过“欠我一枚铜币”“我喜欢桂花酿”，隔天再回来，他会主动提起。
- 每次回复都会基于真实召回的记忆，而不是模型凭空编造，因此“被记住”的感觉是真实可核对的。

## 2. 技术分工

| 组件 | 作用 |
| --- | --- |
| **Dify（必选）** | 承担全部对话流程编排：接收用户输入 → HTTP 请求召回记忆 → LLM 角色扮演生成回复 → HTTP 请求写入记忆 → 返回答案。DSL 见 [`dsl/memory-tavern.yml`](dsl/memory-tavern.yml)。 |
| **PowerContext（必选其一，本作品选择）** | 提供跨会话的长期记忆：`/remember` 把每轮对话写为 Memory 条目；`/recall` 按当前问题做 FTS 检索并合并近期记忆，返回给 Dify 作为提示词上下文。后端见 [`backend/app.py`](backend/app.py)。 |

选择 PowerContext 的作品不额外要求 seekdb；本作品未声明使用 seekdb。

## 3. 文件清单

| 文件 | 用途 |
| --- | --- |
| `dsl/memory-tavern.yml` | Dify 应用 DSL（advanced-chat），导入后即可看到完整流程。 |
| `backend/app.py` | PowerContext HTTP 适配层（FastAPI），提供 `/recall`、`/remember`、`/health`。 |
| `backend/requirements.txt` | 后端依赖（固定 PowerContext v1.2.0 提交）。 |
| `backend/smoke_test.py` | 不需要 Dify 的后端端到端冒烟测试。 |
| `validation.md` | 可逐步执行的验证样例与预期表现。 |

## 4. 运行环境

- Dify：社区版 / 自托管，建议 **0.15 及以上**（DSL `version: 0.1.2`）。云端版导入时若提示版本差异，请按页面提示升级 DSL。
- Python：3.11 或 3.12（推荐 3.12）。
- 模型：任意 OpenAI 兼容的 Chat 模型（DSL 默认占位 `openai / gpt-4o-mini`，导入后请重新绑定你自己的模型 provider）。
- 无需在线 Embedding 或 Rerank 服务；后端使用 SQLite FTS 检索。

## 5. 启动步骤

### 5.1 启动 PowerContext 记忆后端

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8099
```

验证后端：

```bash
curl http://127.0.0.1:8099/health
# {"status":"ok"}
```

数据默认写入 `backend/data/memory_tavern.db`；可通过环境变量 `MEMORY_TAVERN_DATA` 指定其他目录。删除该目录即可重置所有记忆。

### 5.2 导入 Dify 应用

1. 打开 Dify → 工作室 → 创建应用 → **导入 DSL 文件**，选择 `dsl/memory-tavern.yml`。
2. 进入应用后，打开「掌柜阿墨」LLM 节点，重新选择你的模型与 provider（默认的 `gpt-4o-mini` 只是占位）。
3. 检查两个 HTTP Request 节点的地址：
   - Dify 用 Docker 本地部署：`http://host.docker.internal:8099/recall` 和 `.../remember`（DSL 默认值）。
   - Dify 与后端在同一台机器且直接运行：改成 `http://127.0.0.1:8099/...`。
   - Dify 云端版：需要把后端部署到公网可访问地址，并相应替换 URL。
4. 保存并发布应用，打开聊天窗口。

> 不需要配置 API Key：后端只暴露本地记忆接口。请勿在 DSL 中填写真实密钥。

## 6. 验证样例（摘要）

完整步骤与预期输出见 [`validation.md`](validation.md)。核心验证：

1. **第一次会话**：发送“我叫阿岚，是一名迷路的旅人，最喜欢桂花酿。”——阿墨会称呼你并回应。
2. **结束会话，新建一个全新对话**（Dify 同一用户身份）。
3. 发送“还记得我吗？我叫什么名字？我最喜欢喝什么？”——阿墨应当说出“阿岚”和“桂花酿”。
4. **核对技术作用**：后端日志应出现一次 `/remember` 与一次 `/recall`；`backend/data/memory_tavern.db` 中存在该用户的 Memory 条目。

## 7. 可复现性与已知限制

- `backend/smoke_test.py` 直接使用真实嵌入的 PowerContext Runtime，不依赖 Dify 即可验证记忆读写链路。
- 召回采用「FTS 检索 + 近期记忆列表」的组合，保证中文短句中的人名/物品也能被带回；不依赖 Embedding 服务。
- 每个 Dify 用户（`sys.user_id`）对应一个独立 PowerContext Scope，不同用户之间记忆隔离。
- 当前版本一次只保存“玩家说 + 掌柜回应”的整轮文本，不做事实抽取；如需更结构化的玩家档案，可后续在 `/remember` 中增加抽取逻辑。
- 验证时如果希望从零开始，使用一个新的 Dify 用户或新的 `player_id` 即可。

## 8. 来源与改动

- PowerContext：固定使用 `oceanbase/powercontext` 提交 `9db1753434162c0aa7c9f1189a1722e617880a52`（v1.2.0），后端仅调用其公开 Runtime 接口。
- Dify DSL 参考了公开示例的节点结构（[dzh-gitcode/dify-workflows](https://github.com/dzh-gitcode/dify-workflows)），并按本作品流程重新编写；未复用其中任何业务逻辑或密钥。
- 所有示例对话与验证数据均为本项目自造。
