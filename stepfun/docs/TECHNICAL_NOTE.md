# 一页技术说明：StepKB 端侧知识库

## 1. 模型与量化

- **模型来源**：Hugging Face `Xenova/bge-small-zh-v1.5`（Transformers.js ONNX 版本，上游 `BAAI/bge-small-zh-v1.5`），revision `75c43b069aac4d136ba6bc1122f995fedcfd2781`，License MIT，输出 512 维。
- **量化方案**：仓库提供同一模型的 FP32 基线、FP16 权重转换、INT8 动态量化三个 ONNX 变体；FP16 用于 WebGPU，INT8（`model_quantized.onnx`，权重 INT8 + 动态激活量化）用于 WASM。INT8 无需校准集，`npm run setup:model` 会记录每个文件的 SHA-256。

| 精度 | 模型体积 | 压缩比（相对 FP32） | Recall@5 | nDCG@5 | MRR@10 | Top-1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| FP32 基线 | 90.46 MB | 1.00× | 0.9667 | 0.9323 | 0.9278 | 0.9000 |
| FP16 | 45.30 MB | 2.00× | 0.9667 | 0.9323 | 0.9278 | 0.9000 |
| INT8 | 22.90 MB | 3.95× | 0.9667 | 0.9280 | 0.9259 | 0.9000 |

质量评测使用内置 30 篇文档、30 条中文查询，文档级标签，按余弦相似度排序；INT8 的 Recall@5 与 FP32 持平，nDCG@5 仅下降 **0.0043**，检索质量无明显下降。

## 2. 端侧运行

- **运行时**：Transformers.js 3.7.5，模型在 Web Worker 中执行，主线程保持响应；文档和查询 embedding 均在浏览器本地计算，无云端推理 API。
- **后端选择**：启动时检测 `navigator.gpu` 与 `requestAdapter()`；可用则 `device: "webgpu", dtype: "fp16"`，不可用或初始化失败则自动降级 `device: "wasm", dtype: "q8"`。界面实时显示后端、精度和降级原因，也可手动切换复验。已在 Chrome `--disable-gpu --disable-webgpu` 环境实测：适配器不可用时自动选择 WASM/INT8，界面显示原因，查询流程正常。
- **模型加载**：模型文件由本机 `/models` 静态服务提供，`env.allowRemoteModels=false`，HTTP 长缓存；首次 WebGPU 加载（清空 Cache Storage）**665 ms**，热加载 **411 ms**。

## 3. seekdb 使用

- **接入**：`seekdb-js` 1.4.0；Windows 使用 server 模式（seekdb 1.3.0 本地 server，`127.0.0.1:2881/test`），Linux/macOS 可切换嵌入式模式，Docker 方式见 README。
- **集合结构**：每个知识库为独立 `kb_*` 集合；向量索引 `HNSW(dimension=512, distance=cosine, m=16, ef_construction=200, ef_search=64)`；全文索引 `IK analyzer (smart mode)`。
- **混合检索**：查询时提交查询文本 + 查询向量，调用 `collection.hybridSearch({ query: { whereDocument }, knn: { queryEmbeddings }, rank: { rrf } })`；向量召回、全文召回、RRF 融合全部在 seekdb 内完成，客户端不拉取两路结果自行拼合。
- **刷新与增量**：写入采用确定性 ID + `upsert`，重复导入幂等；每批写入后调用 `refresh_index()`，30 篇首次导入 refresh **312.6 ms**，新文档在刷新后立即可检索。

## 4. 状态与优化

- **状态**：当前知识库名保存于 localStorage；切换、清空、删除均按集合名路由，连续导入和切换后的检索结果与当前知识库一致。
- **优化**：Web Worker + 8 条/批的 embedding 批处理；模型本地托管与 HTTP 缓存；写入按 32 条/批提交；索引统一 refresh；检索固定开启 RRF（rankWindowSize=20/40，rankConstant=60）。
- **实测**（Windows 11 10.0.26200，Chromium 146，NVIDIA Blackwell，24 核；30 篇文档、20 条查询、batch=8）：

| 配置 | Embedding 吞吐 | seekdb P50 / P95 | 端到端 P50 / P95 |
| --- | ---: | ---: | ---: |
| WebGPU / FP16 | 317.8 条/s | 3.62 / 4.87 ms | 15.3 / 17.8 ms |
| WASM / INT8 | 17.86 条/s | 3.56 / 4.19 ms | 15.1 / 19.6 ms |

WebGPU 相对 WASM 的 embedding 吞吐提升约 **17.8×**；短查询的端到端延迟主要受查询向量化与 HTTP 往返影响，两者均在 20 ms 内。完整原始数据见 `docs/web-benchmark.json`、`docs/cli-benchmark.json` 与 `docs/quality-results.json`；实验均来自提交应用的实际运行，记录 P50/P95，未只选取最快一次。
