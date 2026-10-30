#!/usr/bin/env node
/**
 * Node-side benchmark for the API + seekdb layer.
 * It uses the same INT8 model to produce embeddings, then measures HTTP round-trips
 * and the database-reported hybrid search latency. Browser GPU timing is measured
 * separately by the in-app "运行性能基准" button.
 *
 * Usage: node scripts/benchmark.mjs [--keep]
 */
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { pipeline, env } from "@huggingface/transformers";
import { SAMPLE_CORPUS, SAMPLE_QUERIES } from "../web/src/sampleCorpus.js";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const BASE = process.env.APP_URL || "http://127.0.0.1:5178";
const MODEL_ID = process.env.MODEL_ID || "bge-small-zh-v1.5";
const KEEP = process.argv.includes("--keep");

env.localModelPath = path.join(ROOT, "models");
env.allowRemoteModels = false;
env.allowLocalModels = true;

function percentile(values, p) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  return Number(sorted[Math.min(sorted.length - 1, Math.ceil((p / 100) * sorted.length) - 1)].toFixed(2));
}

function mean(values) {
  return Number((values.reduce((sum, value) => sum + value, 0) / values.length).toFixed(2));
}

async function request(pathname, options = {}) {
  const response = await fetch(`${BASE}${pathname}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(`${pathname}: HTTP ${response.status} ${payload.error || ""}`);
  return payload;
}

async function embed(extractor, texts, batchSize = 8) {
  const startedAt = performance.now();
  const vectors = [];
  const batchMs = [];
  for (let offset = 0; offset < texts.length; offset += batchSize) {
    const batch = texts.slice(offset, offset + batchSize);
    const t0 = performance.now();
    const output = await extractor(batch, { pooling: "cls", normalize: true });
    const dim = output.dims[output.dims.length - 1];
    for (let index = 0; index < batch.length; index += 1) {
      vectors.push(Array.from(output.data.subarray(index * dim, (index + 1) * dim), (v) => Number(v.toFixed(7))));
    }
    batchMs.push(Number((performance.now() - t0).toFixed(2)));
  }
  return { vectors, totalMs: Number((performance.now() - startedAt).toFixed(2)), batchMs };
}

async function main() {
  const health = await request("/api/health");
  if (!health.ok) throw new Error(`seekdb 未连接: ${health.seekdb.error}`);
  const name = `kb_bench_${Date.now().toString(36)}`;
  await request("/api/kbs", { method: "POST", body: JSON.stringify({ name }) });
  console.log(`[bench] temporary knowledge base: ${name}`);

  const loadStarted = performance.now();
  const extractor = await pipeline("feature-extraction", MODEL_ID, {
    device: "cpu",
    dtype: "q8",
    pooling: "cls",
    normalize: true,
  });
  const modelLoadMs = Number((performance.now() - loadStarted).toFixed(2));

  const docs = SAMPLE_CORPUS.map((doc) => `${doc.title}\n${doc.text}`);
  const docEmbedding = await embed(extractor, docs, 8);
  const documents = SAMPLE_CORPUS.map((doc, index) => ({
    id: `bench-${doc.id}`,
    text: docs[index],
    metadata: { source: "benchmark", title: doc.title, category: doc.category, chunkIndex: 0, chunkCount: 1 },
    embedding: docEmbedding.vectors[index],
  }));
  const insertStart = performance.now();
  const added = await request(`/api/kbs/${name}/documents`, {
    method: "POST",
    body: JSON.stringify({ documents }),
  });
  const insertTotalMs = Number((performance.now() - insertStart).toFixed(2));

  const queries = SAMPLE_QUERIES.slice(0, 20);
  const queryEmbedding = await embed(extractor, queries, 8);
  await request(`/api/kbs/${name}/search`, {
    method: "POST",
    body: JSON.stringify({ query: queries[0], embedding: queryEmbedding.vectors[0], topK: 5 }),
  });
  const dbTimes = [];
  const httpTimes = [];
  const top1 = [];
  for (let index = 0; index < queries.length; index += 1) {
    const startedAt = performance.now();
    const response = await request(`/api/kbs/${name}/search`, {
      method: "POST",
      body: JSON.stringify({ query: queries[index], embedding: queryEmbedding.vectors[index], topK: 5 }),
    });
    httpTimes.push(Number((performance.now() - startedAt).toFixed(2)));
    dbTimes.push(response.timings.dbMs);
    top1.push(response.results[0]?.metadata?.title || null);
  }

  const result = {
    generatedAt: new Date().toISOString(),
    environment: { node: process.version, platform: process.platform, arch: process.arch, model: MODEL_ID, dtype: "int8" },
    corpus: { documents: documents.length, queries: queries.length },
    modelLoadMs,
    embedding: {
      totalMs: docEmbedding.totalMs,
      perTextMs: Number((docEmbedding.totalMs / docs.length).toFixed(2)),
      textsPerSecond: Number((docs.length / (docEmbedding.totalMs / 1000)).toFixed(2)),
      batchMs: docEmbedding.batchMs,
    },
    indexWrite: { httpTotalMs: insertTotalMs, insertMs: added.timings.insertMs, refreshMs: added.timings.refreshMs },
    search: {
      dbP50Ms: percentile(dbTimes, 50),
      dbP95Ms: percentile(dbTimes, 95),
      dbMeanMs: mean(dbTimes),
      httpP50Ms: percentile(httpTimes, 50),
      httpP95Ms: percentile(httpTimes, 95),
      httpMeanMs: mean(httpTimes),
      rawDbMs: dbTimes,
      rawHttpMs: httpTimes,
      top1Titles: top1,
    },
  };

  await fs.mkdir(path.join(ROOT, "docs"), { recursive: true });
  await fs.writeFile(path.join(ROOT, "docs", "cli-benchmark.json"), `${JSON.stringify(result, null, 2)}\n`);
  console.log(JSON.stringify(result, null, 2));
  console.log("[bench] wrote docs/cli-benchmark.json");

  if (!KEEP) {
    await request(`/api/kbs/${name}`, { method: "DELETE" });
    console.log(`[bench] removed ${name}`);
  }
}

main().catch((error) => {
  console.error(`[bench] FAIL: ${error.stack || error.message}`);
  process.exit(1);
});
