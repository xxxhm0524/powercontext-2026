# 订单查询服务规格

本文件是订单查询服务的规格来源（Spec-Driven Development）。每个 `SPEC` 条目都是可独立引用的规格单元；更新条目后重新导入索引，上下文模块必须返回更新后的内容。

## SPEC-ORD-001 — 订单列表默认排序

`list_orders` 默认按 `created_at` 倒序返回，时间相同时按 `order_id` 倒序，保证分页结果稳定。

## SPEC-ORD-002 — 按状态筛选

`list_orders` 必须支持可选参数 `status`：

- 仅返回 `status` 与参数完全匹配的订单。
- `status` 必须是 `pending`、`paid`、`shipped`、`cancelled` 之一。
- 传入未知状态时必须抛出 `ValueError`，不能静默返回空列表。

## SPEC-ORD-003 — 按最低金额筛选

`list_orders` 必须支持可选参数 `min_total`：

- 仅返回 `total >= min_total` 的订单。
- `min_total` 允许 `Decimal`、字符串或整数输入，内部统一转为 `Decimal`。
- `min_total` 为负数时抛出 `ValueError`；为 0 时等价于不筛选金额。

## SPEC-ORD-004 — 分页与兼容性

`list_orders` 在筛选后执行 `offset` / `limit` 分页：

- `limit` 必须是 1 到 100 之间的整数。
- `offset` 必须是非负整数。
- 原有默认排序、`summarize_by_status` 和非法分页参数校验必须保持兼容。

## SPEC-ORD-005 — 组合筛选

当 `status` 与 `min_total` 同时提供时，取两个条件的交集，再按默认排序分页，不得改变任一条件的边界行为。
