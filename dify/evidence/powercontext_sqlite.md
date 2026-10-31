# PowerContext SQLite 持久化核对

数据库文件：`D:\oceanbase\tmp\dify-evidence-data\memory_tavern.db`

## 关键表行数

- `pc_scopes`: 3 rows
- `pc_scope_creation_requests`: 3 rows
- `pc_memory_entry_heads`: 2 rows
- `pc_memory_entry_versions`: 2 rows
- `pc_memory_entry_fts`: 2 rows

## Memory 条目（dify-demo-user 的真实写入）

- `mem_ent_7866f3de135441a9a63b3cbd6dc66b1b` [episode] 玩家说：给我讲讲雾港的故事吧，我想在那里找一条船。
掌柜回应：雾港的船都藏在雾里，等风停了才肯露面。
- `mem_ent_9d3ef40985e44434932a26db34a92622` [episode] 玩家说：我叫阿岚，是一名迷路的旅人，最喜欢桂花酿。身上只剩一枚铜币，先欠着酒钱吧。
掌柜回应：阿岚，桂花酿给你留着，铜币的事我也记着。

## Scope 记录

- `scp_6y5q636vhe6r1h3rbd9tbv9qxw` | Default | Default context
- `scp_5dr30rjb56qf23vssjvxewm641` | Memory Tavern · dify-demo-user | Cross-session role-play memories for one tavern guest
- `scp_3v2e93a2ttwnerypz6ewmrmr6j` | Memory Tavern · another-demo-user | Cross-session role-play memories for one tavern guest

## 结论

以上记录来自真实 SQLite 数据库；`pc_memory_entry_versions.text` 即 Dify 通过 `/remember` 写入的用户原话与掌柜回复。