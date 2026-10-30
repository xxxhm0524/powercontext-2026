# PowerContext 状态写入与复用记录

- 操作次数：12
- PowerContext SQLite：`D:\oceanbase\powercontext-eco\minimax\.runtime\powercontext-validation.db`

| 时间 | 动作 | scope | entry | task | status |
| --- | --- | --- | --- | --- | --- |
| 2026-10-30T14:26:50.929961+00:00 | open | `scp_193jtwb6e3p9jtb8ztd6kk584d` | `` |  |  |
| 2026-10-30T14:26:50.934696+00:00 | load_miss | `scp_193jtwb6e3p9jtb8ztd6kk584d` | `` | TASK-ORDER-FILTER-001 |  |
| 2026-10-30T14:26:50.958294+00:00 | save | `scp_193jtwb6e3p9jtb8ztd6kk584d` | `mem_ent_6710f61b4b4f412995a3f581eb974b05` | TASK-ORDER-FILTER-001 | context_ready |
| 2026-10-30T14:26:52.810674+00:00 | open | `scp_193jtwb6e3p9jtb8ztd6kk584d` | `` |  |  |
| 2026-10-30T14:26:52.827712+00:00 | load_hit | `scp_193jtwb6e3p9jtb8ztd6kk584d` | `` | TASK-ORDER-FILTER-001 |  |
| 2026-10-30T14:27:00.745707+00:00 | open | `scp_193jtwb6e3p9jtb8ztd6kk584d` | `` |  |  |
| 2026-10-30T14:27:00.764199+00:00 | load_hit | `scp_193jtwb6e3p9jtb8ztd6kk584d` | `` | TASK-ORDER-FILTER-001 |  |
| 2026-10-30T14:27:15.941476+00:00 | open | `scp_193jtwb6e3p9jtb8ztd6kk584d` | `` |  |  |
| 2026-10-30T14:27:15.958468+00:00 | load_hit | `scp_193jtwb6e3p9jtb8ztd6kk584d` | `` | TASK-ORDER-FILTER-001 |  |
| 2026-10-30T14:27:15.990921+00:00 | save | `scp_193jtwb6e3p9jtb8ztd6kk584d` | `mem_ent_321f84112bfa4ee6a119320838c81b8e` | TASK-ORDER-FILTER-001 | verified |
| 2026-10-30T14:27:17.820106+00:00 | open | `scp_193jtwb6e3p9jtb8ztd6kk584d` | `` |  |  |
| 2026-10-30T14:27:17.836113+00:00 | load_hit | `scp_193jtwb6e3p9jtb8ztd6kk584d` | `` | TASK-ORDER-FILTER-001 |  |

说明：`save` 是写入，`load_hit` 是另一个进程中的重启读取；两次 `state-show` 均由独立 CLI 进程执行。
