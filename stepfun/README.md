# StepKB · 端侧 AI 推理 × seekdb 混合检索

2026 OceanBase 数据库大赛 · StepFun（阶跃星辰）赛题：**端侧 AI 推理性能优化与 seekdb 混合检索**（20 分）。

应用完成「导入语料 → 浏览器本地向量化 → 写入 seekdb → 向量 + 全文混合检索」的完整流程。模型推理完全在浏览器内完成，不调用任何云端推理 API；向量、原文与元数据统一写入 seekdb，混合检索由数据库内部执行 RRF 融合。

## 功能

- **浏览器本地 embedding**：Transformers.js 3.7.5 + `bge-small-zh-v1.5`（512 维），Web Worker 内运行。
- **WebGPU 优先 / WASM 自动降级**：优先 `WebGPU + FP16`；不支持 WebGPU 时自动切换 `WASM + INT8`，界面显示当前后端与降级原因，也可手动切换验证。
- **INT8 / FP16 量化**：报告 FP32、FP16、INT8 三种权重的体积、压缩比与检索质量变化。
- **seekdb 数据层**：通过官方 `seekdb-js` 1.4.0 接入；HNSW 向量索引（cosine）+ IK 中文全文索引。
- **数据库内混合检索**：`collection.hybridSearch()` 在 seekdb 内完成向量召回、全文召回与 RRF 融合，客户端不拼接两路结果。
- **增量写入与索引刷新**：确定性文档 ID + `upsert`，重复导入幂等；每批写入后调用 `refresh_index()`，新文档立即可检索。
- **多知识库 / 会话状态**：`kb_*` 集合隔离，支持创建、切换、清空、删除；当前知识库保存于 localStorage。
- **性能基准**：应用内一键测量模型加载、embedding 吞吐、seekdb 检索延迟、端到端延迟；默认区分首次加载与热请求。

界面预览：

![StepKB 应用界面](docs/screenshots/app-overview.png)

## 架构

```text
┌──────────────────────────── Browser ────────────────────────────┐
│  React UI                                                       │
│    │ postMessage                                                │
│    ▼                                                            │
│  Web Worker ── Transformers.js ── ONNX Runtime Web              │
│                 ├─ WebGPU / FP16  (优先)                        │
│                 └─ WASM / INT8    (自动降级)                    │
│    │ 文档向量 / 查询向量（Float32Array）                          │
│    ▼ HTTP /api                                                  │
└────┼────────────────────────────────────────────────────────────┘
     ▼
┌──────────────────────── Node.js API ────────────────────────────┐
│  Express 静态服务 + REST API                                    │
│    │ seekdb-js 1.4.0                                            │
│    ▼                                                            │
│  seekdb（嵌入式 / server / OceanBase 兼容模式）                   │
│    ├─ HNSW 向量索引（512 维，cosine）                            │
│    ├─ IK 全文索引                                               │
│    └─ DBMS_HYBRID_SEARCH（RRF rank fusion）                     │
└─────────────────────────────────────────────────────────────────┘
```

**职责边界**：embedding 在浏览器 Worker 中计算；Node 服务只负责接收向量、写入 seekdb 和执行数据库检索，不做任何模型推理。

## 快速开始

### 1. 安装依赖

```bash
cd stepfun
npm install
```

仓库已提供 `.npmrc`（`legacy-peer-deps=true`），用于规避 `@seekdb/default-embed` 的 workspace 协议 peer 依赖问题。

### 2. 获取模型文件（约 166 MB）

```bash
npm run setup:model
```

默认从 `https://hf-mirror.com` 下载 `Xenova/bge-small-zh-v1.5` 的 FP32 / FP16 / INT8 三个 ONNX 变体；如可直连 Hugging Face：

```bash
HF_MIRROR=https://huggingface.co npm run setup:model
```

文件会写入 `models/bge-small-zh-v1.5/`（已 gitignore），并生成 `model-manifest.json`（含每个文件的 SHA-256）。

### 3. 准备 seekdb

#### 方式 A：Windows（推荐，server 模式）

seekdb 官方暂不支持 Windows 嵌入式模式。下载 `seekdb-1.3.0.0-100000092026051510-win64.msi`（[GitHub Release](https://github.com/oceanbase/seekdb/releases/tag/v1.3.0)），解压/安装后直接以普通用户启动 server：

```powershell
seekdb.exe --base-dir=D:/seekdb-data --nodaemon --port=2881 `
  --parameter memory_limit=2G --parameter cpu_count=4
```

首次启动会初始化数据目录。默认账号 `root`，密码为空。保持该窗口运行。

#### 方式 B：Linux / macOS 嵌入式模式

```bash
cp .env.example .env
# 修改 SEEKDB_MODE=embedded
npm install   # 首次安装会按需下载 seekdb 原生绑定
```

嵌入模式数据存放在 `SEEKDB_PATH`（默认 `./data/seekdb`）。

#### 方式 C：Docker（Linux 服务器）

```bash
docker compose up -d seekdb
```

镜像 `oceanbase/seekdb:latest`，端口 2881，默认 root 空密码；数据保存在 Docker volume。

### 4. 配置并启动应用

```bash
cp .env.example .env
# Windows 使用 server 模式；Linux 可改为 embedded
npm run build
npm start
```

打开 <http://127.0.0.1:5178>。

`.env` 关键字段：

```ini
SEEKDB_MODE=server
SEEKDB_HOST=127.0.0.1
SEEKDB_PORT=2881
SEEKDB_USER=root
SEEKDB_PASSWORD=
SEEKDB_DATABASE=test
PORT=5178
MODEL_ID=bge-small-zh-v1.5
MODEL_DIM=512
```

### 开发模式

```bash
npm run dev   # 同时启动 API (5178) 和 Vite (5179)
```

## 使用流程

1. 点击「加载示例语料」，载入 30 篇内置中文文档。
2. 点击「开始导入」：浏览器 Worker 分批（batch=8）计算 embedding，进度条显示向量化 / 写入 seekdb / 索引刷新三个阶段。
3. 导入完成后输入问题，点击「混合检索」：查询向量在浏览器生成，seekdb 执行 `hybridSearch` 返回 RRF 排序结果与原文。
4. 在右侧「端侧推理」卡片切换 `WebGPU / FP16` 与 `WASM / INT8`，验证两条后端路径。
5. 点击「运行性能基准」，在当前后端下运行 30 篇 embedding + 20 次检索；结果写入 localStorage，并在界面展示 P50/P95。

## 验收项对照

| 验收要求 | 实现 |
| --- | --- |
| 完整流程 | 导入文本 → 本地向量化 → seekdb 写入 → 查询 → 排序结果 + 原文 |
| 本地推理 | `embedder.worker.js` 中 Transformers.js 计算全部 embedding，代码无云端推理调用 |
| 模型量化 | 提供 FP32/FP16/INT8 三种 ONNX 权重；体积、压缩比、Recall@5 / nDCG@5 见技术说明 |
| 后端与降级 | `detectWebGPU()` → 失败后自动 `WASM + q8`；界面显示当前后端和降级原因 |
| seekdb 数据层 | `seekdb-js` + Schema（HNSW + IK fulltext）；`hybridSearch` 数据库内融合 |
| 状态与刷新 | 确定性 ID + upsert；每批 `refresh_index()`；`kb_*` 集合隔离，切换/清空/删除 |
| 可复现性 | `npm run setup:model`、`docker-compose.yml`、`.env.example`、`npm run build && npm start` |

## 目录结构

```text
stepfun/
├─ server/
│  ├─ index.mjs          # Express API + 静态服务
│  ├─ kb-service.mjs     # seekdb 连接、集合、写入、混合检索
│  ├─ config.mjs         # 环境配置
│  └─ model-info.mjs     # 模型体积信息
├─ web/
│  ├─ src/App.jsx        # 主界面
│  ├─ src/embedder.worker.js   # Transformers.js Worker（WebGPU / WASM）
│  ├─ src/embedderClient.js    # Worker Promise 封装
│  ├─ src/chunking.js          # 文本分块与文件解析
│  ├─ src/sampleCorpus.js      # 30 篇示例语料 + 30 条示例查询
│  └─ src/styles.css
├─ scripts/
│  ├─ fetch-model.mjs    # 下载 FP32/FP16/INT8 模型 + SHA-256 清单
│  ├─ eval-quality.mjs   # 量化前后检索质量对比
│  ├─ benchmark.mjs      # Node 侧 API/seekdb 基准
│  ├─ test-api.mjs       # 真实 seekdb + INT8 模型的 API 冒烟测试
│  └─ prepare-assets.mjs # 复制 ONNX Runtime WASM 资源
├─ docs/
│  ├─ TECHNICAL_NOTE.md  # 一页技术说明
│  ├─ quality-results.md # 量化质量对比结果
│  ├─ web-benchmark.json # 浏览器端 WebGPU/WASM 实测
│  └─ cli-benchmark.json # Node/seekdb 基准
└─ docker-compose.yml
```

## 验证命令

```bash
# API + seekdb + 真实 INT8 模型端到端冒烟（需先 npm start）
node scripts/test-api.mjs

# 量化前后质量对比（写入 docs/quality-results.{json,md}）
node scripts/eval-quality.mjs

# Node 侧 API/seekdb 基准（写入 docs/cli-benchmark.json）
node scripts/benchmark.mjs
```

本机实测环境与结果摘要见 [`docs/TECHNICAL_NOTE.md`](docs/TECHNICAL_NOTE.md)：

- FP32 → FP16 压缩 **2.00×**，INT8 压缩 **3.95×**（90.46 MB → 45.30 MB → 22.90 MB）。
- 30 篇 / 30 查询的检索质量：Recall@5 三者均为 **0.9667**；INT8 的 nDCG@5 相对 FP32 仅下降 **0.0043**。
- 30 篇文档 embedding：WebGPU/FP16 **317.8 条/s**，WASM/INT8 **17.86 条/s**（约 **17.8×**）。
- seekdb 混合检索 P50 **3.56–3.62 ms**，P95 **4.19–4.87 ms**；端到端 P50 约 **15 ms**。

> Windows 官方暂不支持嵌入式 seekdb，请使用 server 模式；上述结果来自 seekdb 1.3.0 Windows server + seekdb-js 1.4.0 真实运行。
