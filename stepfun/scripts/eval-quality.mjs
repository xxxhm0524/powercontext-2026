#!/usr/bin/env node
/**
 * Compare retrieval quality of the FP32 / FP16 / INT8 model variants.
 *
 * The evaluation uses the built-in 30-document sample corpus and 30 hand-written
 * queries. For each precision we embed every document and query locally, rank
 * documents by cosine similarity, and report Recall@5, nDCG@5, MRR@10 and Top-1.
 *
 * This script is an offline quality check only. The web app itself always uses
 * the browser runtime (WebGPU/FP16 or WASM/INT8) and never calls a cloud API.
 */
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { pipeline, env } from "@huggingface/transformers";
import { SAMPLE_CORPUS } from "../web/src/sampleCorpus.js";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const MODEL_ID = process.env.MODEL_ID || "bge-small-zh-v1.5";
const OUT_DIR = path.join(ROOT, "docs");

env.localModelPath = path.join(ROOT, "models");
env.allowRemoteModels = false;
env.allowLocalModels = true;

const VARIANTS = [
  { name: "FP32 baseline", precision: "fp32", dtype: "fp32" },
  { name: "FP16", precision: "fp16", dtype: "fp16" },
  { name: "INT8 dynamic", precision: "int8", dtype: "q8" },
];

const EVAL_CASES = [
  { query: "seekdb 支持哪些检索方式", ids: ["seekdb-intro"] },
  { query: "OceanBase 如何保证高可用和强一致", ids: ["oceanbase-arch"] },
  { query: "HNSW 的 ef_search 参数有什么作用", ids: ["hnsw"] },
  { query: "为什么文本向量要做 L2 归一化", ids: ["cosine", "embedding-normalize"] },
  { query: "RRF 怎么融合两路检索结果", ids: ["rrf"] },
  { query: "长文档应该怎么切分成知识库片段", ids: ["chunking"] },
  { query: "WebGPU 在浏览器里怎么加速模型推理", ids: ["webgpu"] },
  { query: "Transformers.js 支持哪些推理后端", ids: ["transformersjs"] },
  { query: "INT8 量化会让模型体积缩小多少", ids: ["int8"] },
  { query: "FP16 半精度推理有什么好处", ids: ["fp16"] },
  { query: "bge-small-zh 模型输出多少维向量", ids: ["bge-model"] },
  { query: "RAG 检索增强生成中检索质量为什么重要", ids: ["rag"] },
  { query: "混合检索适合什么场景", ids: ["hybrid-search"] },
  { query: "IK 分词器的 smart 模式是什么", ids: ["ik-tokenizer"] },
  { query: "新写入的文档什么时候可以被搜索到", ids: ["refresh-index"] },
  { query: "为什么要把模型推理放在 Web Worker", ids: ["web-worker"] },
  { query: "模型首次加载为什么比较慢", ids: ["model-cache"] },
  { query: "embedding 为什么要做批处理", ids: ["batch-embedding"] },
  { query: "向量维度对存储成本有什么影响", ids: ["vector-dim"] },
  { query: "本地优先架构如何保护数据隐私", ids: ["local-first"] },
  { query: "seekdb-js 提供哪些 API", ids: ["seekdb-js"] },
  { query: "seekdb 的 Docker 镜像怎么启动", ids: ["deploy-docker"] },
  { query: "全文索引和 LIKE 模糊匹配有什么区别", ids: ["sql-fulltext"] },
  { query: "Top-K 的 K 应该怎么选", ids: ["topk"] },
  { query: "WebGPU 不可用时应用如何自动降级", ids: ["wasm-fallback"] },
  { query: "性能测试要记录哪些阶段和指标", ids: ["benchmark"] },
  { query: "多知识库切换要注意什么", ids: ["session-state"] },
  { query: "端侧 AI 有哪些优势和限制", ids: ["edge-ai"] },
  { query: "seekdb 能不能嵌入式运行", ids: ["seekdb-intro"] },
  { query: "怎样评估量化前后的检索质量变化", ids: ["int8", "benchmark"] },
];

const DOC_TEXTS = SAMPLE_CORPUS.map((doc) => `${doc.title}\n${doc.text}`);
const DOC_IDS = SAMPLE_CORPUS.map((doc) => doc.id);

async function embedAll(extractor, texts) {
  const output = await extractor(texts, { pooling: "cls", normalize: true });
  const dims = output.dims;
  const dim = dims[dims.length - 1];
  const vectors = [];
  for (let index = 0; index < texts.length; index += 1) {
    vectors.push(Float32Array.from(output.data.subarray(index * dim, (index + 1) * dim)));
  }
  return vectors;
}

function dot(a, b) {
  let sum = 0;
  for (let index = 0; index < a.length; index += 1) sum += a[index] * b[index];
  return sum;
}

function rankDocuments(docVectors, queryVector) {
  return DOC_IDS
    .map((id, index) => ({ id, score: dot(docVectors[index], queryVector), index }))
    .sort((a, b) => b.score - a.score);
}

function evaluate(rankings) {
  let recall5 = 0;
  let ndcg5 = 0;
  let mrr10 = 0;
  let top1 = 0;
  for (let index = 0; index < EVAL_CASES.length; index += 1) {
    const expected = new Set(EVAL_CASES[index].ids);
    const ranked = rankings[index].map((item) => item.id);
    const top5 = ranked.slice(0, 5);
    const found = top5.filter((id) => expected.has(id)).length;
    recall5 += found / expected.size;
    if (ranked[0] && expected.has(ranked[0])) top1 += 1;

    let dcg = 0;
    for (let rank = 0; rank < Math.min(5, ranked.length); rank += 1) {
      if (expected.has(ranked[rank])) dcg += 1 / Math.log2(rank + 2);
    }
    let idcg = 0;
    for (let rank = 0; rank < Math.min(expected.size, 5); rank += 1) idcg += 1 / Math.log2(rank + 2);
    ndcg5 += idcg ? dcg / idcg : 0;

    const firstHit = ranked.slice(0, 10).findIndex((id) => expected.has(id));
    mrr10 += firstHit >= 0 ? 1 / (firstHit + 1) : 0;
  }
  const total = EVAL_CASES.length;
  return {
    queries: total,
    recallAt5: Number((recall5 / total).toFixed(4)),
    ndcgAt5: Number((ndcg5 / total).toFixed(4)),
    mrrAt10: Number((mrr10 / total).toFixed(4)),
    top1Accuracy: Number((top1 / total).toFixed(4)),
  };
}

async function runVariant(variant) {
  console.log(`[eval] ${variant.name} (${variant.dtype}) loading...`);
  const startedAt = performance.now();
  const extractor = await pipeline("feature-extraction", MODEL_ID, {
    device: "cpu",
    dtype: variant.dtype,
    pooling: "cls",
    normalize: true,
  });
  const loadMs = Number((performance.now() - startedAt).toFixed(2));
  const embedStart = performance.now();
  const docVectors = await embedAll(extractor, DOC_TEXTS);
  const queryVectors = await embedAll(extractor, EVAL_CASES.map((item) => item.query));
  const embedMs = Number((performance.now() - embedStart).toFixed(2));
  const rankings = queryVectors.map((vector) => rankDocuments(docVectors, vector));
  const metrics = evaluate(rankings);
  const top1Disagreement = rankings.filter((ranking, index) => {
    const expected = new Set(EVAL_CASES[index].ids);
    return !expected.has(ranking[0]?.id);
  }).length;
  console.log(`[eval] ${variant.name}: ${JSON.stringify(metrics)} embed=${embedMs}ms load=${loadMs}ms`);
  if (extractor.dispose) await extractor.dispose().catch(() => {});
  return { ...variant, loadMs, embedMs, ...metrics, top1Misses: top1Disagreement };
}

async function main() {
  const results = [];
  for (const variant of VARIANTS) {
    try {
      results.push(await runVariant(variant));
    } catch (error) {
      console.error(`[eval] ${variant.name} failed: ${error.message}`);
      results.push({ ...variant, error: error.message });
    }
  }

  const baseline = results.find((item) => item.precision === "fp32");
  for (const result of results) {
    if (result.error) continue;
    result.deltaRecallAt5 = baseline && baseline.recallAt5 != null ? Number((result.recallAt5 - baseline.recallAt5).toFixed(4)) : null;
    result.deltaNdcgAt5 = baseline && baseline.ndcgAt5 != null ? Number((result.ndcgAt5 - baseline.ndcgAt5).toFixed(4)) : null;
  }

  const output = {
    generatedAt: new Date().toISOString(),
    model: { id: MODEL_ID, repo: "Xenova/bge-small-zh-v1.5" },
    corpus: { documents: DOC_TEXTS.length, queries: EVAL_CASES.length },
    method: "Cosine similarity ranking over the built-in corpus; labels at document level.",
    results,
  };
  await fs.mkdir(OUT_DIR, { recursive: true });
  await fs.writeFile(path.join(OUT_DIR, "quality-results.json"), `${JSON.stringify(output, null, 2)}\n`);

  const lines = [
    "# 量化前后检索质量对比",
    "",
    `生成时间：${output.generatedAt}`,
    "",
    `模型：${output.model.id}（${output.model.repo}）`,
    "",
    `评测集：${output.corpus.documents} 篇文档、${output.corpus.queries} 条查询，文档级标签，按余弦相似度排序。`,
    "",
    "| 精度 | Recall@5 | nDCG@5 | MRR@10 | Top-1 | 相对 FP32 Recall 变化 | 向量化耗时 |",
    "| --- | --- | --- | --- | --- | --- | --- |",
  ];
  for (const result of results) {
    if (result.error) {
      lines.push(`| ${result.name} | 失败 | — | — | — | — | ${result.error} |`);
      continue;
    }
    lines.push(
      `| ${result.name} | ${result.recallAt5.toFixed(4)} | ${result.ndcgAt5.toFixed(4)} | ${result.mrrAt10.toFixed(4)} | ${result.top1Accuracy.toFixed(4)} | ${result.deltaRecallAt5 >= 0 ? "+" : ""}${result.deltaRecallAt5.toFixed(4)} | ${result.embedMs.toFixed(0)} ms |`,
    );
  }
  lines.push("");
  lines.push("> 说明：这是一个小规模、可复现的内部评测集，用于比较同一模型不同精度之间的相对差异；绝对值不代表公开榜单成绩。");
  await fs.writeFile(path.join(OUT_DIR, "quality-results.md"), `${lines.join("\n")}\n`);
  console.log(`[eval] wrote ${path.join(OUT_DIR, "quality-results.json")}`);
  console.log(`[eval] wrote ${path.join(OUT_DIR, "quality-results.md")}`);
}

main().catch((error) => {
  console.error(`[eval] ${error.stack || error.message}`);
  process.exit(1);
});
