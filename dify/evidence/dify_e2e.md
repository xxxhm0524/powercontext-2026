# Dify 端到端运行记录（真实 Dify 0.15.3 + 真实 PowerContext 后端）

本记录来自本机实际启动的 **Dify 0.15.3**（Flask API，端口 5001）与 **记忆酒馆后端**（FastAPI，端口 8099）。
Dify 通过 `POST /console/api/apps/imports` 导入 `dsl/memory-tavern.yml`，导入结果为 `status: completed`，然后发布工作流并通过 Service API 发起两轮独立会话。

> 说明：本机没有可用的外部模型 Key，因此 LLM 节点在本次验收中指向一个本地 OpenAI 兼容桩模型（端口 8100），仅用于让回复内容确定、可核对；Dify 本身、两个 HTTP Request 节点、FastAPI 后端、PowerContext Runtime 与 SQLite 持久化都是真实运行。评审按 README 第 5.3 节把 LLM 节点绑定到自己的模型即可。

## 一、DSL 导入

```json
{
  "id": "a5a368ca-ec00-4437-9df8-3cef04c8b5c9",
  "status": "completed",
  "app_id": "3cf78293-31c9-4e54-91c8-e54342ee84d2",
  "current_dsl_version": "0.1.5",
  "imported_dsl_version": "0.1.5",
  "error": ""
}
```

导入完成后发布工作流：

```text
POST /console/api/apps/3cf78293-31c9-4e54-91c8-e54342ee84d2/workflows/publish
→ 200 {"result":"success","created_at":1793412781}
```

> 本次本机验收把 DSL 中的 `host.docker.internal` 替换为 `127.0.0.1`（因为 Dify 与后端都直接运行在 Windows 主机上）；提交的 `dsl/memory-tavern.yml` 默认值是 `host.docker.internal`，README 5.2 节已给出三种部署方式对应的 URL。

## 二、会话 1：第一次见面

请求：

```http
POST http://127.0.0.1:5001/v1/chat-messages
Authorization: Bearer app-****（评审自己创建的应用 API Key）
Content-Type: application/json

{
  "inputs": {},
  "query": "我叫阿岚，是一名迷路的旅人，最喜欢桂花酿。身上只剩一枚铜币，先欠着酒钱吧。",
  "response_mode": "blocking",
  "user": "dify-e2e-user",
  "auto_generate_name": false
}
```

响应（HTTP 200）：

```json
{
  "event": "message",
  "conversation_id": "10fd5c30-2085-43a8-9865-ccf7fed6f31f",
  "mode": "advanced-chat",
  "answer": "阿岚，桂花酿给你留着呢。今晚雾大，先暖暖手。你还欠我一枚铜币，不过不急着还——先说说今天想聊什么？",
  "metadata": {
    "usage": {"prompt_tokens": 440, "completion_tokens": 53, "total_tokens": 493}
  }
}
```

## 三、会话 2：全新对话，同一 Dify 用户

新建会话（`conversation_id` 为空 → Dify 生成新会话），同一 `user: dify-e2e-user`。

请求：

```json
{
  "inputs": {},
  "query": "掌柜的，还记得我吗？我叫什么名字？我最喜欢喝什么？",
  "response_mode": "blocking",
  "user": "dify-e2e-user",
  "auto_generate_name": false
}
```

响应（HTTP 200）：

```json
{
  "event": "message",
  "conversation_id": "9c11894c-2878-4d4d-bbb0-dad379725a6d",
  "mode": "advanced-chat",
  "answer": "阿岚，你回来啦。桂花酿我一直给你温着，铜币的事也没忘。今天想听雾港的什么故事？",
  "metadata": {
    "usage": {"prompt_tokens": 500, "completion_tokens": 43, "total_tokens": 543}
  }
}
```

**关键点**：第二次会话是一个全新的 `conversation_id`，Dify 的会话窗口为空；阿墨仍能叫出「阿岚」并提到「桂花酿」，证明信息来自 PowerContext 的跨会话记忆，而非 Dify 会话上下文。

## 四、Dify 工作流节点执行记录（来自 Dify 的 PostgreSQL）

两次成功运行的 `workflow_runs`：

| workflow_run_id | 状态 | 节点数 | tokens | 耗时(s) |
| --- | --- | --- | --- | --- |
| `58a7baba-f1cd-4380-8c35-e42d75bb5edd` | succeeded | 5 | 543 | 0.124 |
| `f203ef57-1521-4342-9d5e-074a8a9bd209` | succeeded | 5 | 493 | 0.390 |

节点执行（以第二次「跨会话召回」运行为例）：

| index | 节点 | 类型 | 状态 | 耗时(s) | 输出摘要 |
| --- | --- | --- | --- | --- | --- |
| 1 | 开始 | start | succeeded | 0.014 | `sys.query = 掌柜的，还记得我吗？我叫什么名字？...` |
| 2 | 召回记忆 | http-request | succeeded | 0.043 | `status_code: 200`，body 为 `【常客簿】姓名：阿岚...` |
| 3 | 掌柜阿墨 | llm | succeeded | 0.035 | 生成包含「阿岚」「桂花酿」的回复 |
| 4 | 记住这一轮 | http-request | succeeded | 0.033 | `{"status":"saved","entry_id":"mem_ent_7f1ce2f028ce410fb1fdd56b22dd2c02",...}` |
| 5 | 直接回复 | answer | succeeded | 0.004 | `{"answer":"阿岚，你回来啦。..."}` |

这直接证明：Dify 承担了完整编排，且 PowerContext 的召回结果确实进入了 LLM 提示词、写入结果确实返回了真实 `entry_id`。

## 五、后端日志（同一时刻）

```text
2026-10-31 18:13:09,714 INFO memory_tavern recall player=dify-e2e-user query_chars=37 context_chars=48
2026-10-31 18:13:10,068 INFO memory_tavern remember player=dify-e2e-user user_chars=37 reply_chars=49 entry=mem_ent_de6c9a15484e4344bc08f9b2c25a0c0a
2026-10-31 18:13:21,105 INFO memory_tavern recall player=dify-e2e-user query_chars=25 context_chars=127
2026-10-31 18:13:21,173 INFO memory_tavern remember player=dify-e2e-user user_chars=25 reply_chars=39 entry=mem_ent_7f1ce2f028ce410fb1fdd56b22dd2c02
```

## 六、PowerContext 实际存储（/stats）

```json
{
  "player_id": "dify-e2e-user",
  "scope_id": "scp_5p9s5mh5k53e1qq6h6b42323xh",
  "memory_count": 2,
  "latest_entries": [
    {
      "entry_id": "mem_ent_7f1ce2f028ce410fb1fdd56b22dd2c02",
      "text": "玩家说：掌柜的，还记得我吗？我叫什么名字？我最喜欢喝什么？\n掌柜回应：阿岚，你回来啦。桂花酿我一直给你温着，铜币的事也没忘。今天想听雾港的什么故事？"
    },
    {
      "entry_id": "mem_ent_de6c9a15484e4344bc08f9b2c25a0c0a",
      "text": "玩家说：我叫阿岚，是一名迷路的旅人，最喜欢桂花酿。身上只剩一枚铜币，先欠着酒钱吧。\n掌柜回应：阿岚，桂花酿给你留着呢。今晚雾大，先暖暖手。你还欠我一枚铜币，不过不急着还——先说说今天想聊什么？"
    }
  ]
}
```

## 七、结论

- **Dify 侧**：DSL `status: completed` 导入；五个节点（开始 → 召回记忆 → 掌柜阿墨 → 记住这一轮 → 直接回复）全部 `succeeded`。
- **PowerContext 侧**：`/recall` 返回的常客簿进入 LLM prompt；`/remember` 写入真实用户输入与 LLM 节点的实际输出（本次本机验证中为桩模型输出）；`memory_count = 2`。
- **跨会话**：两次独立 `conversation_id`，同一 `user`，第二次回答包含第一次会话的姓名与喜好。
