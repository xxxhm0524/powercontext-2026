# 订单查询服务（示例业务工程）

这是 MiniMax 赛题验证样例使用的业务工程。它自身不依赖第三方库，只用 Python
标准库实现一个订单查询服务；测试使用 `pytest`。

## 运行

```bash
cd minimax/demo_project
python -m pytest -q
```

## 任务

当前仓库的 `demo_project` 是修改后的版本；修改前的完整快照在
`validation/snapshots/before/demo_project`。目标任务是按照 `specs/orders.md`
为 `list_orders` 增加 `status` 和 `min_total` 筛选，并保持分页、排序与
`summarize_by_status` 的原有行为。

## 文件

- `specs/orders.md`：规格条目（SPEC-ORD-001 ~ 005）。
- `src/order_service.py`：订单查询实现。
- `tests/test_orders_regression.py`：修改前后都必须通过的回归测试。
- `tests/test_orders_filters.py`：目标功能测试，在修改前快照中失败，修改后通过。
