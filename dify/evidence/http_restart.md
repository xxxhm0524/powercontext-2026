# 后端重启后的记忆恢复记录

生成时间：2026-10-31T17:26:17

后端停止后使用同一 `MEMORY_TAVERN_DATA` 重新启动，验证 PowerContext Scope 幂等复用。

## 1. 重启后健康检查

`GET /health` → **HTTP 200**

```text
{"status":"ok","powercontext":"ready","database":"D:\\oceanbase\\tmp\\dify-evidence-data\\memory_tavern.db"}
```

## 2. 重启后查看原玩家记忆

`GET /stats/dify-demo-user` → **HTTP 200**

```text
{"player_id":"dify-demo-user","scope_id":"scp_5dr30rjb56qf23vssjvxewm641","memory_count":2,"latest_entries":[{"entry_id":"mem_ent_7866f3de135441a9a63b3cbd6dc66b1b","text":"玩家说：给我讲讲雾港的故事吧，我想在那里找一条船。\n掌柜回应：雾港的船都藏在雾里，等风停了才肯露面。"},{"entry_id":"mem_ent_9d3ef40985e44434932a26db34a92622","text":"玩家说：我叫阿岚，是一名迷路的旅人，最喜欢桂花酿。身上只剩一枚铜币，先欠着酒钱吧。\n掌柜回应：阿岚，桂花酿给你留着，铜币的事我也记着。"}]}
```

## 3. 重启后跨会话召回

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
