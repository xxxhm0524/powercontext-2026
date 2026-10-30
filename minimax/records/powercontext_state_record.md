# PowerContext 状态写入与复用记录

- 操作次数：12
- PowerContext SQLite：`D:\oceanbase\powercontext-eco\minimax\.runtime\powercontext-validation.db`

| 时间 | 动作 | scope | entry | task | status |
| --- | --- | --- | --- | --- | --- |
| 2026-10-30T13:48:14.415544+00:00 | open | `scp_4eh24qarc9svgvdgvnbee5z2vq` | `` |  |  |
| 2026-10-30T13:48:14.419717+00:00 | load_miss | `scp_4eh24qarc9svgvdgvnbee5z2vq` | `` | TASK-ORDER-FILTER-001 |  |
| 2026-10-30T13:48:14.440245+00:00 | save | `scp_4eh24qarc9svgvdgvnbee5z2vq` | `mem_ent_9b88f158ab55473193270fbc9a6f3a55` | TASK-ORDER-FILTER-001 | context_ready |
| 2026-10-30T13:48:15.729757+00:00 | open | `scp_4eh24qarc9svgvdgvnbee5z2vq` | `` |  |  |
| 2026-10-30T13:48:15.744670+00:00 | load_hit | `scp_4eh24qarc9svgvdgvnbee5z2vq` | `` | TASK-ORDER-FILTER-001 |  |
| 2026-10-30T13:48:20.681431+00:00 | open | `scp_4eh24qarc9svgvdgvnbee5z2vq` | `` |  |  |
| 2026-10-30T13:48:20.694958+00:00 | load_hit | `scp_4eh24qarc9svgvdgvnbee5z2vq` | `` | TASK-ORDER-FILTER-001 |  |
| 2026-10-30T13:49:07.237052+00:00 | open | `scp_4eh24qarc9svgvdgvnbee5z2vq` | `` |  |  |
| 2026-10-30T13:49:07.250078+00:00 | load_hit | `scp_4eh24qarc9svgvdgvnbee5z2vq` | `` | TASK-ORDER-FILTER-001 |  |
| 2026-10-30T13:49:07.276338+00:00 | save | `scp_4eh24qarc9svgvdgvnbee5z2vq` | `mem_ent_9964a41aeabc4e50a835ed97e8919598` | TASK-ORDER-FILTER-001 | verified |
| 2026-10-30T13:49:08.662104+00:00 | open | `scp_4eh24qarc9svgvdgvnbee5z2vq` | `` |  |  |
| 2026-10-30T13:49:08.674904+00:00 | load_hit | `scp_4eh24qarc9svgvdgvnbee5z2vq` | `` | TASK-ORDER-FILTER-001 |  |

说明：`save` 是写入，`load_hit` 是另一个进程中的重启读取；两次 `state-show` 均由独立 CLI 进程执行。
