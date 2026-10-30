# PowerContext 状态写入与复用记录

- 操作次数：12
- PowerContext SQLite：`D:\oceanbase\powercontext-eco\minimax\.runtime\powercontext-validation.db`

| 时间 | 动作 | scope | entry | task | status |
| --- | --- | --- | --- | --- | --- |
| 2026-10-30T15:36:20.582406+00:00 | open | `scp_1c4n7pj900k4a55tyzcjmg95sb` | `` |  |  |
| 2026-10-30T15:36:20.587595+00:00 | load_miss | `scp_1c4n7pj900k4a55tyzcjmg95sb` | `` | TASK-ORDER-FILTER-001 |  |
| 2026-10-30T15:36:20.616346+00:00 | save | `scp_1c4n7pj900k4a55tyzcjmg95sb` | `mem_ent_7d9b9e333fc44fb3a9bdec9c0d65a0e4` | TASK-ORDER-FILTER-001 | context_ready |
| 2026-10-30T15:36:22.641721+00:00 | open | `scp_1c4n7pj900k4a55tyzcjmg95sb` | `` |  |  |
| 2026-10-30T15:36:22.660711+00:00 | load_hit | `scp_1c4n7pj900k4a55tyzcjmg95sb` | `` | TASK-ORDER-FILTER-001 |  |
| 2026-10-30T15:36:30.623205+00:00 | open | `scp_1c4n7pj900k4a55tyzcjmg95sb` | `` |  |  |
| 2026-10-30T15:36:30.641013+00:00 | load_hit | `scp_1c4n7pj900k4a55tyzcjmg95sb` | `` | TASK-ORDER-FILTER-001 |  |
| 2026-10-30T15:36:41.694603+00:00 | open | `scp_1c4n7pj900k4a55tyzcjmg95sb` | `` |  |  |
| 2026-10-30T15:36:41.715009+00:00 | load_hit | `scp_1c4n7pj900k4a55tyzcjmg95sb` | `` | TASK-ORDER-FILTER-001 |  |
| 2026-10-30T15:36:41.753809+00:00 | save | `scp_1c4n7pj900k4a55tyzcjmg95sb` | `mem_ent_0080324530cb434d84cfe3e0f9282707` | TASK-ORDER-FILTER-001 | verified |
| 2026-10-30T15:36:43.784315+00:00 | open | `scp_1c4n7pj900k4a55tyzcjmg95sb` | `` |  |  |
| 2026-10-30T15:36:43.805502+00:00 | load_hit | `scp_1c4n7pj900k4a55tyzcjmg95sb` | `` | TASK-ORDER-FILTER-001 |  |

说明：`save` 是写入，`load_hit` 是另一个进程中的重启读取；两次 `state-show` 均由独立 CLI 进程执行。
