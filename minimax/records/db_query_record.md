# seekdb 查询与索引使用记录

- 查询次数：2
- 数据库模式：`seekdb-server:gw0.apac.seekdb.ai:2881/d0_t2ywT0r3AcT1`

| 时间 | 操作 | 参数 | 返回行数 | 耗时 (ms) |
| --- | --- | --- | --- | --- |
| 2026-10-30T09:55:52.522118+00:00 | search | `["list_orders", "pagination", "min_total", "filtering", "listing", "minimum", "filters", "orders", "status", "amount"...` | 24 | 935.01 |
| 2026-10-30T09:55:58.899953+00:00 | search | `["filtering", "filters", "status", "review", "filter", "state", "状态筛选", "状态筛", "态筛选", "状态", "态筛", "筛选", 400]` | 15 | 95.07 |

## 完整 SQL（最近一次）

```sql
SELECT c.chunk_id, c.kind, c.source_path, c.symbol, c.title, c.content, c.start_line, c.end_line, c.metadata, agg.matched_terms, agg.term_hits FROM ( SELECT chunk_id, COUNT(DISTINCT term) AS matched_terms, SUM(tf) AS term_hits FROM sdd_terms WHERE term IN (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) GROUP BY chunk_id ) AS agg JOIN sdd_chunks AS c ON c.chunk_id = agg.chunk_id ORDER BY agg.matched_terms DESC, agg.term_hits DESC LIMIT %s
```
