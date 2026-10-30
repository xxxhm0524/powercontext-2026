# MiniMax SDD 验证报告

- run_id: `20261030-133700`
- 时间: 2026-10-30T13:37:51.218922+00:00
- 结果: **5/6**

| 验收项 | 结果 | 证据 |
| --- | --- | --- |
| runnable | PASS | init, context and validation sample executed via seekdb-server:gw0.apac.seekdb.ai:2881/d0_t2ywT0r3AcT1; init_chunks=24, context_exit=0, state_exit=0 |
| minimax_participation | FAIL | no live MiniMax transcript (set MINIMAX_API_KEY and rerun with --use-minimax) |
| context_correct | PASS | required sources present; specs=['SPEC-ORD-001', 'SPEC-ORD-002', 'SPEC-ORD-003', 'SPEC-ORD-004', 'SPEC-ORD-005'] code=['<module>', 'Order', 'list_orders', 'summarize_by_status'] tests=11; spec_update=True |
| database_participation | PASS | mode=seekdb-server:gw0.apac.seekdb.ai:2881/d0_t2ywT0r3AcT1; chunks={'code': 4, 'spec': 5, 'test': 15}; query_log_lines=2 |
| state_reuse | PASS | initial status=context_ready; final status=verified |
| code_change_effective | PASS | before target={'failed': 5} regression={'passed': 6}; after target={'passed': 5} regression={'passed': 6} full={'passed': 11} |

MiniMax capture failed:  _chat_anthropic
    self._raise_for_status(response)
    ~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^
  File "D:\oceanbase\powercontext-eco\minimax\sdd_context\minimax_client.py", line 264, in _raise_for_status
    raise MiniMaxError(f"MiniMax HTTP {response.status_code}: {body}")
sdd_context.minimax_client.MiniMaxError: MiniMax HTTP 404: {"type":"error","error":{"type":"not_found_error","message":"The model \"MiniMax-M2.5\" is no longer available. (2069)"},"request_id":"0733d0ab30c66cb801fa8de5e336afb8"}

