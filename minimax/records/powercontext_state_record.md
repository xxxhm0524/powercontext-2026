# PowerContext 状态写入与复用记录

- 操作次数：12
- PowerContext SQLite：`D:\oceanbase\powercontext-eco\minimax\.runtime\powercontext-validation.db`

| 时间 | 动作 | scope | entry | task | status |
| --- | --- | --- | --- | --- | --- |
| 2026-10-30T13:37:17.926245+00:00 | open | `scp_05nz75zarr3ves7xd0v2k7daff` | `` |  |  |
| 2026-10-30T13:37:17.929896+00:00 | load_miss | `scp_05nz75zarr3ves7xd0v2k7daff` | `` | TASK-ORDER-FILTER-001 |  |
| 2026-10-30T13:37:17.946471+00:00 | save | `scp_05nz75zarr3ves7xd0v2k7daff` | `mem_ent_beb8f3577e5744408c7eaf22230ccd68` | TASK-ORDER-FILTER-001 | context_ready |
| 2026-10-30T13:37:19.231959+00:00 | open | `scp_05nz75zarr3ves7xd0v2k7daff` | `` |  |  |
| 2026-10-30T13:37:19.243067+00:00 | load_hit | `scp_05nz75zarr3ves7xd0v2k7daff` | `` | TASK-ORDER-FILTER-001 |  |
| 2026-10-30T13:37:27.428451+00:00 | open | `scp_05nz75zarr3ves7xd0v2k7daff` | `` |  |  |
| 2026-10-30T13:37:27.441408+00:00 | load_hit | `scp_05nz75zarr3ves7xd0v2k7daff` | `` | TASK-ORDER-FILTER-001 |  |
| 2026-10-30T13:37:49.200023+00:00 | open | `scp_05nz75zarr3ves7xd0v2k7daff` | `` |  |  |
| 2026-10-30T13:37:49.212300+00:00 | load_hit | `scp_05nz75zarr3ves7xd0v2k7daff` | `` | TASK-ORDER-FILTER-001 |  |
| 2026-10-30T13:37:49.236381+00:00 | save | `scp_05nz75zarr3ves7xd0v2k7daff` | `mem_ent_443532151ddc44fd94dd96619733bfd0` | TASK-ORDER-FILTER-001 | verified |
| 2026-10-30T13:37:50.525873+00:00 | open | `scp_05nz75zarr3ves7xd0v2k7daff` | `` |  |  |
| 2026-10-30T13:37:50.538232+00:00 | load_hit | `scp_05nz75zarr3ves7xd0v2k7daff` | `` | TASK-ORDER-FILTER-001 |  |

说明：`save` 是写入，`load_hit` 是另一个进程中的重启读取；两次 `state-show` 均由独立 CLI 进程执行。
