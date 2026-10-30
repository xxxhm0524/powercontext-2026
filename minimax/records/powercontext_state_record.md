# PowerContext 状态写入与复用记录

- 操作次数：12
- PowerContext SQLite：`D:\oceanbase\powercontext-eco\minimax\.runtime\powercontext-validation.db`

| 时间 | 动作 | scope | entry | task | status |
| --- | --- | --- | --- | --- | --- |
| 2026-10-30T09:55:44.416429+00:00 | open | `scp_423mecv5yrmdsax2gjn2c1vmss` | `` |  |  |
| 2026-10-30T09:55:44.420335+00:00 | load_miss | `scp_423mecv5yrmdsax2gjn2c1vmss` | `` | TASK-ORDER-FILTER-001 |  |
| 2026-10-30T09:55:44.440196+00:00 | save | `scp_423mecv5yrmdsax2gjn2c1vmss` | `mem_ent_da0bf8b4fe0c4a01b939fa0075dbc001` | TASK-ORDER-FILTER-001 | context_ready |
| 2026-10-30T09:55:45.725656+00:00 | open | `scp_423mecv5yrmdsax2gjn2c1vmss` | `` |  |  |
| 2026-10-30T09:55:45.738512+00:00 | load_hit | `scp_423mecv5yrmdsax2gjn2c1vmss` | `` | TASK-ORDER-FILTER-001 |  |
| 2026-10-30T09:55:54.902617+00:00 | open | `scp_423mecv5yrmdsax2gjn2c1vmss` | `` |  |  |
| 2026-10-30T09:55:54.915329+00:00 | load_hit | `scp_423mecv5yrmdsax2gjn2c1vmss` | `` | TASK-ORDER-FILTER-001 |  |
| 2026-10-30T09:56:04.524915+00:00 | open | `scp_423mecv5yrmdsax2gjn2c1vmss` | `` |  |  |
| 2026-10-30T09:56:04.537239+00:00 | load_hit | `scp_423mecv5yrmdsax2gjn2c1vmss` | `` | TASK-ORDER-FILTER-001 |  |
| 2026-10-30T09:56:04.562652+00:00 | save | `scp_423mecv5yrmdsax2gjn2c1vmss` | `mem_ent_2a6b9791db244841926a14e185b1565e` | TASK-ORDER-FILTER-001 | verified |
| 2026-10-30T09:56:05.873944+00:00 | open | `scp_423mecv5yrmdsax2gjn2c1vmss` | `` |  |  |
| 2026-10-30T09:56:05.886574+00:00 | load_hit | `scp_423mecv5yrmdsax2gjn2c1vmss` | `` | TASK-ORDER-FILTER-001 |  |

说明：`save` 是写入，`load_hit` 是另一个进程中的重启读取；两次 `state-show` 均由独立 CLI 进程执行。
