# 一页技术说明

## 模块结构

`minimax/sdd_context/` 提供四层能力：

1. **语料解析（corpus.py）**：将 Markdown 规格按 `SPEC-*` 标题拆条；用 Python AST
   将源码与测试按函数/类拆块，保留真实路径、符号和行号。
2. **材料索引（seekdb_store.py）**：在 seekdb 中建立 `sdd_chunks` 与 `sdd_terms`
   两张表。`sdd_terms` 是 term-frequency 倒排索引；检索使用单条 SQL
   `JOIN + GROUP BY` 返回候选块，Python 只做重排。
3. **上下文选择（selector.py）**：根据任务中的中英文关键词（含同义词扩展）查询
   seekdb，按匹配词数、词频、标题/符号/路径命中、规格 ID、测试目标进行加权，
   输出规格、代码、测试三类来源及每条来源的 `path:line`。
4. **状态与开发闭环（state.py / dev_workflow.py / minimax_client.py）**：
   PowerContext 以 `SDD_STATE|{json}` 形式追加任务状态版本；MiniMax 客户端读取
   上下文生成 unified diff；测试在修改前后分别执行并写入验证报告。

## 上下文选择方式

- 查询词由英文标识符、中文 2/3-gram 与领域同义词组成（如“状态→status”“最低金额→
  min_total”），避免依赖重型中文分词器。
- 检索在 seekdb 中执行，不是把语料读进内存后全量匹配；返回的候选块带有
  `matched_terms` 与 `term_hits`。
- 选择阶段额外考虑：规格 ID 精确匹配、测试的 `TARGET_SPECS` 标注、回归测试标记、
  代码模块块与符号块的配套关系。
- 规格被修改并重新导入后，`sdd_chunks` 中旧的规格内容被替换，因此同一查询会返回
  更新后的文本（`run_validation.py` 的 `context_uses_updated_spec` 检查）。

## 三项技术的分工

| 技术 | 在本作品中的实际作用 | 可核对材料 |
| --- | --- | --- |
| **MiniMax** | 读取上下文后生成代码修改 diff；参与实际开发任务 | `records/minimax_dev_record.jsonl`（配置 Key 后生成）、`records/minimax_dev_record.md`、`validation/minimax_output.diff` |
| **seekdb** | 保存规格/代码/测试的块与倒排索引；每次上下文选择执行 SQL 检索 | `records/db_query_record.jsonl`、`records/db_query_record.md`，查询示例含 SQL、参数、行数、耗时 |
| **PowerContext** | 保存任务状态（阶段、已完成、待办、验证结果）；重启后读取并注入上下文 | `records/powercontext_state_record.jsonl`、`records/powercontext_state_record.md`，同一 scope 跨进程读取 |

## 验证样例

业务工程 `demo_project` 是一个订单查询服务。任务是根据 `specs/orders.md` 为
`list_orders` 增加 `status` 与 `min_total` 筛选，同时保持分页与回归兼容。

- 修改前：目标测试 5 个失败（筛选未实现），回归测试 6 个通过。
- 修改后：目标测试 5 个通过，回归测试 6 个通过，全量 11 个通过。
- 状态复用：`state-save` 在一个进程中写入，`state-show` 在另一个进程中读回
  `status=verified` 与完整验证结果。
- 规格更新：临时给 `SPEC-ORD-002` 增加 `review` 条款并重新导入，查询输出包含
  更新后的条款；随后恢复原始语料。

## 入口与可复现性

- CLI：`python -m sdd_context.cli {init,context,state-save,state-show,search,stats}`
- HTTP：`uvicorn scripts.http_server:app`
- 一键验收：`python scripts/run_validation.py [--use-minimax]`
- 依赖版本、数据初始化、测试命令和已知限制见 `minimax/README.md`。
