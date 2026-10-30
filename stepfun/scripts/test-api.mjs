#!/usr/bin/env node
/**
 * End-to-end API smoke test using the real INT8 model and a real seekdb server.
 * Run the app server first, then: node scripts/test-api.mjs
 */
import path from "node:path";
import { fileURLToPath } from "node:url";
import { pipeline, env } from "@huggingface/transformers";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const BASE = process.env.APP_URL || "http://127.0.0.1:5178";
const MODEL_ID = process.env.MODEL_ID || "bge-small-zh-v1.5";

env.localModelPath = path.join(ROOT, "models");
env.allowRemoteModels = false;
env.allowLocalModels = true;

async function request(pathname, options = {}) {
  const response = await fetch(`${BASE}${pathname}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(`${pathname}: HTTP ${response.status} ${payload.error || ""}`);
  return payload;
}

async function embed(extractor, texts) {
  const output = await extractor(texts, { pooling: "cls", normalize: true });
  const dim = output.dims[output.dims.length - 1];
  const vectors = [];
  for (let index = 0; index < texts.length; index += 1) {
    vectors.push(Array.from(output.data.subarray(index * dim, (index + 1) * dim), (v) => Number(v.toFixed(7))));
  }
  return vectors;
}

async function main() {
  const health = await request("/api/health");
  console.log(`[test] health ok=${health.ok} seekdb=${health.seekdb.mode}/${health.seekdb.connected} model ready=${health.model.ready}`);
  if (!health.ok) throw new Error(`seekdb 未连接: ${health.seekdb.error}`);

  const name = `kb_smoke_${Date.now().toString(36)}`;
  console.log(`[test] create ${name}`);
  await request("/api/kbs", { method: "POST", body: JSON.stringify({ name }) });

  const extractor = await pipeline("feature-extraction", MODEL_ID, {
    device: "cpu",
    dtype: "q8",
    pooling: "cls",
    normalize: true,
  });
  const texts = [
    "OceanBase seekdb 支持向量检索和全文检索。",
    "HNSW 是一种分层可导航小世界图索引。",
    "浏览器可以通过 WebGPU 执行端侧 embedding 推理。",
    "不相关的内容：今天食堂的午饭是番茄炒蛋。",
  ];
  const vectors = await embed(extractor, texts);
  const documents = texts.map((text, index) => ({
    id: `smoke-${index}`,
    text,
    metadata: { source: "smoke.txt", title: `片段 ${index}`, chunkIndex: index },
    embedding: vectors[index],
  }));
  const added = await request(`/api/kbs/${name}/documents`, {
    method: "POST",
    body: JSON.stringify({ documents }),
  });
  console.log(`[test] added=${added.added} total=${added.total} refresh=${added.timings.refreshMs}ms`);

  // The same deterministic IDs must update in place rather than duplicate.
  const again = await request(`/api/kbs/${name}/documents`, {
    method: "POST",
    body: JSON.stringify({ documents }),
  });
  if (again.total !== 4) throw new Error(`upsert 后 count 应为 4，实际 ${again.total}`);
  console.log(`[test] idempotent upsert count=${again.total}`);

  // A new batch must become searchable immediately after refresh_index().
  const extraText = "增量文档：seekdb 刷新索引后，新写入的片段可以立即被检索到。";
  const extraVector = (await embed(extractor, [extraText]))[0];
  const extra = await request(`/api/kbs/${name}/documents`, {
    method: "POST",
    body: JSON.stringify({
      documents: [{
        id: "smoke-extra",
        text: extraText,
        metadata: { source: "incremental.txt", title: "增量写入验证", chunkIndex: 0 },
        embedding: extraVector,
      }],
    }),
  });
  console.log(`[test] incremental add total=${extra.total} refresh=${extra.timings.refreshMs}ms`);
  const incrementalSearch = await request(`/api/kbs/${name}/search`, {
    method: "POST",
    body: JSON.stringify({
      query: "增量文档 刷新索引 立即检索",
      embedding: extraVector,
      topK: 3,
    }),
  });
  if (!incrementalSearch.results.some((item) => item.id === "smoke-extra")) {
    throw new Error("增量写入后未能立即检索到新文档");
  }
  console.log("[test] incremental document is searchable after refresh");

  const query = "seekdb 的向量检索能力";
  const queryVector = (await embed(extractor, [query]))[0];
  const search = await request(`/api/kbs/${name}/search`, {
    method: "POST",
    body: JSON.stringify({ query, embedding: queryVector, topK: 3 }),
  });
  console.log(`[test] hybrid search mode=${search.mode} db=${search.timings.dbMs}ms`);
  for (const [index, item] of search.results.entries()) {
    console.log(`       #${index + 1} score=${item.score} ${item.metadata?.title}: ${item.text.slice(0, 36)}`);
  }
  if (!search.results.length) throw new Error("检索结果为空");
  if (!search.results.some((item) => item.text.includes("seekdb"))) {
    throw new Error("Top-3 未包含预期的 seekdb 文档");
  }

  const stats = await request(`/api/kbs/${name}/stats`);
  console.log(`[test] stats count=${stats.count} dim=${stats.dimension}`);
  const listed = await request(`/api/kbs/${name}/documents?limit=10`);
  console.log(`[test] documents listed=${listed.documents.length}`);

  await request(`/api/kbs/${name}`, { method: "DELETE" });
  console.log("[test] PASS");
}

main().catch((error) => {
  console.error(`[test] FAIL: ${error.stack || error.message}`);
  process.exit(1);
});
