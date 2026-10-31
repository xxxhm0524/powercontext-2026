# 记忆酒馆后端 HTTP 运行记录

生成时间：2026-10-31T17:25:19

服务地址：`http://127.0.0.1:8099`

## 1. 健康检查

`GET /health` → **HTTP 200**

```text
{"status":"ok","powercontext":"ready","database":"D:\\oceanbase\\tmp\\dify-evidence-data\\memory_tavern.db"}
```

## 2. 新玩家首次召回（兜底）

`POST /recall` → **HTTP 200**

```text
【常客簿】还是空的。这是你们第一次见面。
请热情地招呼这位旅人，问问他的名字，再问他想喝点什么。
```

## 3. 写入第一轮真实对话

`POST /remember` → **HTTP 200**

```text
{"status":"saved","entry_id":"mem_ent_9d3ef40985e44434932a26db34a92622","memory_artifact_id":"memory"}
```

## 4. 写入第二轮真实对话

`POST /remember` → **HTTP 200**

```text
{"status":"saved","entry_id":"mem_ent_7866f3de135441a9a63b3cbd6dc66b1b","memory_artifact_id":"memory"}
```

## 5. 跨会话召回（同一 player_id）

`POST /recall` → **HTTP 200**

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

## 6. 查看 PowerContext 实际存储

`GET /stats/dify-demo-user` → **HTTP 200**

```text
{"player_id":"dify-demo-user","scope_id":"scp_5dr30rjb56qf23vssjvxewm641","memory_count":2,"latest_entries":[{"entry_id":"mem_ent_7866f3de135441a9a63b3cbd6dc66b1b","text":"玩家说：给我讲讲雾港的故事吧，我想在那里找一条船。\n掌柜回应：雾港的船都藏在雾里，等风停了才肯露面。"},{"entry_id":"mem_ent_9d3ef40985e44434932a26db34a92622","text":"玩家说：我叫阿岚，是一名迷路的旅人，最喜欢桂花酿。身上只剩一枚铜币，先欠着酒钱吧。\n掌柜回应：阿岚，桂花酿给你留着，铜币的事我也记着。"}]}
```

## 7. 第二位玩家的隔离验证

`POST /recall` → **HTTP 200**

```text
【常客簿】还是空的。这是你们第一次见面。
请热情地招呼这位旅人，问问他的名字，再问他想喝点什么。
```

## 8. 非法输入校验

`POST /recall` → **HTTP 422**

```text
{"detail":[{"type":"string_too_short","loc":["player_id"],"msg":"String should have at least 1 character","input":"","ctx":{"min_length":1}}]}
```

## 9. JSON 协议兼容

`POST /recall (JSON)` → **HTTP 200**

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
