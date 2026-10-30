# 验收演示与实测记录

## 3 分钟演示脚本

1. 启动 seekdb server 与 `npm start`，打开 `http://127.0.0.1:5178`。
2. 页面右上显示 `seekdb 已连接` 与 `WebGPU · FP16`（不支持 WebGPU 时显示 `WASM · INT8` 及降级原因）。
3. 点击「加载示例语料」→「开始导入」，展示进度条与导入结果：30 个片段、本地向量化、写入 seekdb、索引刷新耗时。
4. 输入「seekdb 的混合检索是怎么做的？」，点击「混合检索」：展示 5 条排序结果、原文、来源与融合得分；状态条显示 `hybridSearch`。
5. 输入「WebGPU 不可用时如何降级到 WASM？」验证中文全文 + 向量混合检索。
6. 点击右侧「WASM / INT8」，等待模型切换后再次检索，确认核心流程在降级后端仍可运行；再切回 `WebGPU / FP16`。
7. 点击「运行性能基准」，展示模型加载、embedding 吞吐、seekdb P50/P95 与端到端 P50/P95。
8. 新建一个知识库，确认空集合；切回 `stepfun_demo`，确认 30 个片段和检索结果仍属于当前知识库；清空/删除用于验证集合状态管理。

## 本机实测记录（2026-10-30）

### 环境

- Windows 11 `10.0.26200` x64
- Chromium `146.0.7680.80`（ZCode in-app browser，Electron 41.0.3）
- GPU：NVIDIA Blackwell（WebGPU adapter vendor=nvidia）
- 24 逻辑核，`navigator.deviceMemory` = 8 GB
- seekdb server `1.3.0.0`，`127.0.0.1:2881/test`；seekdb-js `1.4.0`
- 示例语料：30 篇 / 30 个片段

### API 冒烟（`node scripts/test-api.mjs`）

```text
[test] health ok=true seekdb=server/true model ready=true
[test] create kb_smoke_mvuvf3bg
[test] added=4 total=4 refresh=417.75ms
[test] hybrid search mode=hybrid db=45.47ms
[test] stats count=4 dim=512
[test] documents listed=4
[test] PASS
```

### 浏览器导入（WebGPU / FP16）

```text
片段 30
本地向量化 824.2 ms
写入 seekdb 127.6 ms
索引刷新 312.6 ms
```

重复导入同一示例语料后，集合 count 仍为 30（upsert 幂等 + refresh_index）。

### 检索（WebGPU / FP16）

```text
最近一次检索 49.4 ms
向量化 26.9 ms · seekdb 18.5 ms
hybridSearch
Top-1: 向量与全文混合检索（0.0325）
Top-2: seekdb 是什么（0.0323）
```

### 自动降级验证（Chrome `--disable-gpu --disable-webgpu`）

```text
embedder.state = ready
embedder.backend = wasm
embedder.dtype = q8
embedder.loadMs = 410.9 ms
界面提示：WebGPU 不可用原因：WebGPU 适配器不可用（可能是软件渲染或显卡被禁用）
查询「WebGPU 不可用时如何降级到 WASM」Top-1 = WASM 降级策略
```

### 性能基准

| 后端 | Embedding | seekdb P50 | seekdb P95 | 端到端 P50 | 端到端 P95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| WebGPU / FP16 | 317.8 条/s | 3.62 ms | 4.87 ms | 15.3 ms | 17.8 ms |
| WASM / INT8 | 17.86 条/s | 3.56 ms | 4.19 ms | 15.1 ms | 19.6 ms |

### 量化质量（`node scripts/eval-quality.mjs`）

| 精度 | Recall@5 | nDCG@5 | MRR@10 | Top-1 |
| --- | ---: | ---: | ---: | ---: |
| FP32 | 0.9667 | 0.9323 | 0.9278 | 0.9000 |
| FP16 | 0.9667 | 0.9323 | 0.9278 | 0.9000 |
| INT8 | 0.9667 | 0.9280 | 0.9259 | 0.9000 |

> 以上数值均由本仓库脚本或应用内基准直接产生，原始 JSON 见 `docs/quality-results.json`、`docs/web-benchmark.json`、`docs/cli-benchmark.json`。
