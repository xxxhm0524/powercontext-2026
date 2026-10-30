# PowerContext 状态写入与复用记录

- 操作次数：12
- PowerContext SQLite：`D:\oceanbase\powercontext-eco\minimax\.runtime\powercontext-validation.db`

| 时间 | 动作 | scope | entry | task | status |
| --- | --- | --- | --- | --- | --- |
| 2026-10-30T15:46:48.551114+00:00 | open | `scp_4hgew62gp3tg8xjby20zj0zgw6` | `` |  |  |
| 2026-10-30T15:46:48.555642+00:00 | load_miss | `scp_4hgew62gp3tg8xjby20zj0zgw6` | `` | TASK-ORDER-FILTER-001 |  |
| 2026-10-30T15:46:48.581081+00:00 | save | `scp_4hgew62gp3tg8xjby20zj0zgw6` | `mem_ent_82a557ea94bb4e5ba04144df50cac792` | TASK-ORDER-FILTER-001 | context_ready |
| 2026-10-30T15:46:50.572201+00:00 | open | `scp_4hgew62gp3tg8xjby20zj0zgw6` | `` |  |  |
| 2026-10-30T15:46:50.589366+00:00 | load_hit | `scp_4hgew62gp3tg8xjby20zj0zgw6` | `` | TASK-ORDER-FILTER-001 |  |
| 2026-10-30T15:46:59.275227+00:00 | open | `scp_4hgew62gp3tg8xjby20zj0zgw6` | `` |  |  |
| 2026-10-30T15:46:59.294050+00:00 | load_hit | `scp_4hgew62gp3tg8xjby20zj0zgw6` | `` | TASK-ORDER-FILTER-001 |  |
| 2026-10-30T15:47:10.363040+00:00 | open | `scp_4hgew62gp3tg8xjby20zj0zgw6` | `` |  |  |
| 2026-10-30T15:47:10.380490+00:00 | load_hit | `scp_4hgew62gp3tg8xjby20zj0zgw6` | `` | TASK-ORDER-FILTER-001 |  |
| 2026-10-30T15:47:10.416557+00:00 | save | `scp_4hgew62gp3tg8xjby20zj0zgw6` | `mem_ent_328829ffec7d4335b5435ab9939d6437` | TASK-ORDER-FILTER-001 | verified |
| 2026-10-30T15:47:12.365096+00:00 | open | `scp_4hgew62gp3tg8xjby20zj0zgw6` | `` |  |  |
| 2026-10-30T15:47:12.382820+00:00 | load_hit | `scp_4hgew62gp3tg8xjby20zj0zgw6` | `` | TASK-ORDER-FILTER-001 |  |

说明：`save` 是写入，`load_hit` 是另一个进程中的重启读取；两次 `state-show` 均由独立 CLI 进程执行。
