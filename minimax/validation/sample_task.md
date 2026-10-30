# 验证样例：订单列表筛选

## 任务描述

在 `validation/snapshots/before/demo_project` 上完成一次局部修改：为
`src/order_service.py` 的 `list_orders` 增加 `status` 与 `min_total` 两个可选筛选
参数，并保持 `SPEC-ORD-004` 的分页、排序与非法参数校验不变。修改后的参考版本在
`validation/snapshots/after/demo_project`。

## 有效规格

上下文输出必须至少包含以下规格来源：

- `SPEC-ORD-002`：按状态筛选（未知状态抛出 `ValueError`）
- `SPEC-ORD-003`：按最低金额筛选（负数抛出 `ValueError`，0 等价于不筛选）
- `SPEC-ORD-004`：分页与兼容性
- `SPEC-ORD-005`：组合筛选取交集

## 必需代码与测试来源

- 代码：`src/order_service.py` 的 `list_orders`
- 目标测试（修改前失败、修改后通过）：
  - `test_filter_by_status_returns_only_matching`
  - `test_filter_by_min_total_excludes_smaller`
  - `test_filter_combined_intersection_and_order`
  - `test_invalid_status_rejected`
  - `test_negative_min_total_rejected`
- 回归测试（修改前后都通过）：
  - `test_default_sort_is_newest_first`
  - `test_pagination_preserves_order`
  - `test_invalid_limit_rejected`
  - `test_negative_offset_rejected`
  - `test_status_summary_unchanged`
  - `test_min_total_zero_is_no_amount_filter`

## 初始数据

- `validation/snapshots/before/demo_project` 是完整的修改前工程；
- `specs/orders.md` 包含 5 个规格条目；
- 测试数据由测试文件内的 `make_orders()` 构造，不依赖外部文件。

## 操作步骤

```bash
cd minimax

# 1. 初始化 seekdb 资料索引
python -m sdd_context.cli init \
  --project-root validation/snapshots/before/demo_project --reset

# 2. 选择开发上下文
python -m sdd_context.cli context \
  --task-id TASK-ORDER-FILTER-001 \
  --query "为订单列表增加按状态和最低金额筛选，需保持分页兼容" \
  --project-root validation/snapshots/before/demo_project \
  --json-out validation/expected_context.json

# 3. 写入任务状态，并在新进程读回
python -m sdd_context.cli state-save \
  --task-id TASK-ORDER-FILTER-001 \
  --status context_ready \
  --completed task_defined \
  --todo implement_filters
python -m sdd_context.cli state-show --task-id TASK-ORDER-FILTER-001

# 4. 修改前测试（预期：目标测试 5 failed，回归 6 passed）
cd validation/snapshots/before/demo_project
python -m pytest -q tests/test_orders_filters.py
python -m pytest -q tests/test_orders_regression.py

# 5. 应用代码差异（或使用 MiniMax 生成的 diff）
cd ../../..
python scripts/apply_reference_change.py
```

`python scripts/run_validation.py` 会自动完成上述全部步骤，并在
`validation/report.json` / `report.md` 中记录每项结果与日志路径。

## 预期结果

| 阶段 | 目标测试 | 回归测试 | 全量 |
| --- | --- | --- | --- |
| 修改前 | 5 failed | 6 passed | 5 failed, 6 passed |
| 修改后 | 5 passed | 6 passed | 11 passed |

上下文输出必须包含第 2 节列出的规格、代码和测试来源；`state` 字段包含
`task_defined`、`context_ready`，重启后的 `state-show` 返回同一状态。

规格更新测试：在 `SPEC-ORD-002` 中追加 `review` 条款并重新导入后，查询
`status review 状态筛选` 必须返回包含该条款的更新文本；验证结束后重新导入原始
规格。

## 重置方法

```bash
# 清空 seekdb 索引并重新导入
python -m sdd_context.cli init --project-root demo_project --reset

# 删除本地 PowerContext 状态（下一轮从空状态开始）
rm -f .runtime/powercontext.db .runtime/powercontext-validation.db
rm -f records/powercontext_state_record.jsonl records/db_query_record.jsonl
```

注意：`.runtime/seekdb.json` 只保存本机临时数据库连接，不会提交到仓库；重新执行
`python scripts/bootstrap_seekdb.py` 可获得新的免费 seekdb 实例。
