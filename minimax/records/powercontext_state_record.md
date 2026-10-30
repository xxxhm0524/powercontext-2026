# PowerContext 状态写入与复用记录

- 操作次数：12
- PowerContext SQLite：`D:\oceanbase\powercontext-eco\minimax\.runtime\powercontext-validation.db`

| 时间 | 动作 | scope | entry | task | status |
| --- | --- | --- | --- | --- | --- |
| 2026-10-30T13:35:22.081851+00:00 | open | `scp_08tby7wet7s0mxt6c3da6wc2fn` | `` |  |  |
| 2026-10-30T13:35:22.086052+00:00 | load_miss | `scp_08tby7wet7s0mxt6c3da6wc2fn` | `` | TASK-ORDER-FILTER-001 |  |
| 2026-10-30T13:35:22.109406+00:00 | save | `scp_08tby7wet7s0mxt6c3da6wc2fn` | `mem_ent_553555eab51f4af2b1a2529224da0b1a` | TASK-ORDER-FILTER-001 | context_ready |
| 2026-10-30T13:35:23.600272+00:00 | open | `scp_08tby7wet7s0mxt6c3da6wc2fn` | `` |  |  |
| 2026-10-30T13:35:23.613320+00:00 | load_hit | `scp_08tby7wet7s0mxt6c3da6wc2fn` | `` | TASK-ORDER-FILTER-001 |  |
| 2026-10-30T13:35:30.886340+00:00 | open | `scp_08tby7wet7s0mxt6c3da6wc2fn` | `` |  |  |
| 2026-10-30T13:35:30.899590+00:00 | load_hit | `scp_08tby7wet7s0mxt6c3da6wc2fn` | `` | TASK-ORDER-FILTER-001 |  |
| 2026-10-30T13:35:40.034940+00:00 | open | `scp_08tby7wet7s0mxt6c3da6wc2fn` | `` |  |  |
| 2026-10-30T13:35:40.047857+00:00 | load_hit | `scp_08tby7wet7s0mxt6c3da6wc2fn` | `` | TASK-ORDER-FILTER-001 |  |
| 2026-10-30T13:35:40.073546+00:00 | save | `scp_08tby7wet7s0mxt6c3da6wc2fn` | `mem_ent_8d7bc1883b0843aab05ba1dbc4556d4f` | TASK-ORDER-FILTER-001 | verified |
| 2026-10-30T13:35:41.411435+00:00 | open | `scp_08tby7wet7s0mxt6c3da6wc2fn` | `` |  |  |
| 2026-10-30T13:35:41.424977+00:00 | load_hit | `scp_08tby7wet7s0mxt6c3da6wc2fn` | `` | TASK-ORDER-FILTER-001 |  |

说明：`save` 是写入，`load_hit` 是另一个进程中的重启读取；两次 `state-show` 均由独立 CLI 进程执行。
