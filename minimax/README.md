# 规有所依：面向软件持续演进的 SDD 上下文管理系统

本目录是 2026 OceanBase 数据库大赛 MiniMax 赛题的参赛作品。模块面向规格驱动开发
（Spec-Driven Development，SDD）：根据开发任务，从 **seekdb** 中检索适用的规格、
代码和测试，结合 **PowerContext** 中保存的任务状态，形成可追溯的开发上下文；再用
**MiniMax** 完成一次真实的代码修改，并通过目标测试与回归测试验证。

## 1. 目录

```
minimax/
├── sdd_context/                 # 上下文模块（CLI + HTTP 入口）
│   ├── corpus.py                # 规格/代码/测试解析
│   ├── seekdb_store.py          # seekdb 倒排索引与 SQL 检索
│   ├── selector.py              # 任务相关上下文选择
│   ├── state.py                 # PowerContext 任务状态持久化
│   ├── minimax_client.py        # MiniMax API 适配器（native/anthropic/openai）
│   ├── dev_workflow.py          # MiniMax 开发与补丁工作流
│   └── cli.py                   # 稳定调用入口
├── demo_project/                # 可运行业务工程（修改后版本）
├── validation/
│   ├── snapshots/before|after/  # 修改前后完整快照
│   ├── sample_task.json         # 验证样例（任务与必需来源）
│   ├── sample_task.md           # 验证样例的操作步骤与预期结果
│   ├── expected_context.json    # 上下文模块的样例输出
│   ├── code_change.patch        # 前后代码差异
│   ├── report.json / report.md  # 最近一次验收结果
│   └── logs/                    # 测试命令、退出码与输出
├── records/                     # MiniMax / seekdb / PowerContext 使用记录
├── scripts/                     # 初始化、验收、记录生成脚本
└── docs/technical_note.md       # 一页技术说明
```

## 2. 环境与依赖

- Python 3.11+
- 仓库根目录（`powercontext`）安装 PowerContext：

  ```bash
  cd <powercontext-repo>
  pip install -e .
  pip install -r minimax/requirements.txt
  ```

- 一个 seekdb / OceanBase 实例。三种方式任选其一：

  1. **免费 seekdb 云实例（推荐，无需账号）**：

     ```bash
     python minimax/scripts/bootstrap_seekdb.py
     ```

     脚本会把连接串写入 `minimax/.runtime/seekdb.json`（已 git-ignore），
     实例有效期 7 天，可重复执行创建新实例。

  2. **已有 seekdb / OceanBase**：设置环境变量

     ```bash
     export SEEKDB_DSN='mysql://user:password@host:2881/database'
     ```

  3. **seekdb 嵌入式模式（Linux/macOS，安装 pylibseekdb）**：

     ```bash
     pip install pyseekdb==1.4.0.post1   # 会自动安装对应平台的 pylibseekdb
     export SEEKDB_PATH=/path/to/seekdb-data
     ```

  说明：PowerContext 自身使用 SQLite 持久化，因此不需要 OceanBase 租户。

## 3. 快速运行（CLI）

所有命令在 `minimax/` 目录执行：

```bash
cd minimax

# 1) 导入规格/代码/测试到 seekdb
python -m sdd_context.cli init --project-root demo_project --reset

# 2) 为任务选择开发上下文（输出 JSON，并带 PowerContext 任务状态）
python -m sdd_context.cli context \
  --task-id TASK-ORDER-FILTER-001 \
  --query "为订单列表增加按状态和最低金额筛选，需保持分页兼容" \
  --project-root demo_project \
  --json-out /tmp/context.json

# 3) 写入任务状态（PowerContext）
python -m sdd_context.cli state-save \
  --task-id TASK-ORDER-FILTER-001 \
  --status context_ready \
  --completed task_defined \
  --todo implement_filters

# 4) 新进程读取状态（重启后复用）
python -m sdd_context.cli state-show --task-id TASK-ORDER-FILTER-001
```

`context` 输出包含：

- `specs`：本次任务适用的规格条目（`SPEC-ORD-002`、`003`、`004`、`005` 等）；
- `code`：需要修改的代码文件/符号（如 `list_orders`）；
- `tests`：用于功能验证与兼容性验证的测试（目标测试 + 回归测试）；
- `state`：从 PowerContext 读取的任务进展、待办和已有验证结果；
- `sources`：每条来源的真实路径与行号。

## 4. 验证样例（一键验收）

```bash
cd minimax
python scripts/run_validation.py
```

脚本会从**空环境**开始：

1. 复制 `validation/snapshots/before/demo_project` 到干净工作区；
2. 初始化 seekdb、导入规格/代码/测试；
3. 运行修改前测试：目标测试 5 个失败、回归测试 6 个通过；
4. 在两个独立进程中写入并读取 PowerContext 状态；
5. 生成上下文并核对必需规格、代码、测试来源；
6. 应用 `validation/code_change.patch`（或 MiniMax 生成的补丁）；
7. 运行修改后测试：目标测试 5 个通过、回归测试 6 个通过、全量 11 个通过；
8. 修改规格并重新导入，验证上下文使用更新后的内容；
9. 输出 `validation/report.json` / `report.md` 与测试日志。

注意：未配置 `MINIMAX_API_KEY` 时，验证脚本会使用参考补丁完成代码效果验证，
并把 `minimax_participation` 标记为失败。要完成全部六项硬性验收，需配置
MiniMax 平台 Key 后运行：

```bash
export MINIMAX_API_KEY='...'
export MINIMAX_BASE_URL='https://api.minimaxi.com/anthropic'
export MINIMAX_MODEL='MiniMax-M3.1-Flash'
python scripts/run_validation.py --use-minimax
```

`--use-minimax` 会通过 `scripts/capture_minimax_dev_record.py` 捕获完整
prompt、响应、usage 和延迟，并把模型返回的 unified diff 应用到工作区后运行测试。

## 5. MiniMax 接入

`MiniMaxClient` 支持三种 API 风格（用 `MINIMAX_API_STYLE` 选择）：

| 风格 | 默认 Base URL | 说明 |
| --- | --- | --- |
| `anthropic`（默认） | `https://api.minimaxi.com/anthropic` | MiniMax 编码套餐的 Anthropic 兼容端点 |
| `native` | `https://api.minimaxi.com/v1` | 原生 `/text/chatcompletion_v2` |
| `openai` | 自定义 | 任意 OpenAI 兼容网关 |

配置：

```bash
export MINIMAX_API_KEY='...'                 # 必填
export MINIMAX_MODEL='MiniMax-M3.1-Flash'          # 默认
export MINIMAX_BASE_URL='https://api.minimaxi.com/anthropic'
export MINIMAX_API_STYLE='anthropic'         # anthropic | native | openai
```

比赛报名学生可通过 OceanBase 社区 Token 领取页
（<https://ask.oceanbase.com/t/topic/35653137>）扫码领取 MiniMax Mplan explore，
按页面要求填写 MiniMax 开放平台 UID。拿到 API Key 后执行：

```bash
python scripts/capture_minimax_dev_record.py \
  --context /tmp/context.json \
  --before-root validation/snapshots/before/demo_project \
  --record records/minimax_dev_record.jsonl \
  --output-diff validation/minimax_output.diff
```

开发记录会落到 `records/minimax_dev_record.jsonl`，再由
`python scripts/build_records.py` 生成可读的 `records/minimax_dev_record.md`。

### 常见错误

| 错误 | 含义 | 处理 |
| --- | --- | --- |
| `401` | API Key 无效，或 Key 与提交的团队空间不一致 | 在同一个团队空间下重新创建 API Key |
| `402 / insufficient_balance_error (1008)` | 账户余额不足，Mplan explore 权益未生效 | 检查领取邮箱里的权益码，在 MiniMax 平台「套餐/兑换」中兑换；确认权益发到的是提交的团队 ID |
| `404 / 2069` | 模型已下线 | 默认会自动回退 `M3.1-Flash → M3 → M2.7`，无需手工处理 |

## 6. HTTP 入口（可选）

```bash
uvicorn scripts.http_server:app --host 127.0.0.1 --port 8765

curl -s http://127.0.0.1:8765/context \
  -H 'Content-Type: application/json' \
  -d '{"task_id":"TASK-ORDER-FILTER-001","query":"为订单列表增加按状态和最低金额筛选"}'
```

接口：

- `POST /context`：返回完整上下文 JSON；
- `GET /state/{task_id}`：读取 PowerContext 状态；
- `POST /state`：追加状态版本；
- `GET /health`：健康检查。

## 7. 已知限制

- Windows 不提供 `pylibseekdb`，请使用 seekdb Server DSN；Linux/macOS 可用嵌入式模式。
- 免费 seekdb 云实例有效期 7 天，过期后重新执行 `scripts/bootstrap_seekdb.py`。
- 真实的 MiniMax 开发记录需要平台 API Key；仓库不包含任何凭据。
- 验证样例的参考补丁只用于展示“修改前后测试变化”，最终提交应使用
  `--use-minimax` 生成的模型补丁与记录。
