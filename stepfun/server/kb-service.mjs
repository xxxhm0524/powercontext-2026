import { SeekdbClient, Schema, VectorIndexConfig, FulltextIndexConfig } from "seekdb";
import fs from "node:fs/promises";
import path from "node:path";
import { config } from "./config.mjs";

const KB_NAME_PATTERN = /^kb_[a-z0-9][a-z0-9_-]{0,60}$/;
const ADD_BATCH_SIZE = 64;

function assertKbName(name) {
  if (!KB_NAME_PATTERN.test(name)) {
    const error = new Error("知识库名称必须以 kb_ 开头，且仅包含小写字母、数字、下划线或连字符（不超过 61 个字符）");
    error.statusCode = 400;
    throw error;
  }
}

function normalizeTopK(value) {
  const topK = Number(value);
  if (!Number.isFinite(topK)) return 10;
  return Math.min(50, Math.max(1, Math.trunc(topK)));
}

/** Strip characters that have special meaning in the full-text query_string syntax. */
export function sanitizeFulltextQuery(value) {
  return String(value || "")
    .replace(/[+\-=&|><!(){}\[\]^"~*?:\\/]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 300);
}

export class KbService {
  constructor(cfg = config) {
    this.cfg = cfg;
    this.client = null;
    this.collectionCache = new Map();
    this.connecting = null;
  }

  async connect() {
    if (this.client) return this.client;
    if (this.connecting) return this.connecting;
    this.connecting = this.#connectInternal();
    try {
      this.client = await this.connecting;
      return this.client;
    } finally {
      this.connecting = null;
    }
  }

  async #connectInternal() {
    const s = this.cfg.seekdb;
    let client;
    if (s.mode === "server") {
      client = new SeekdbClient({
        host: s.host,
        port: s.port,
        user: s.user,
        password: s.password,
        database: s.database,
        ...(s.tenant ? { tenant: s.tenant } : {}),
      });
    } else if (s.mode === "embedded") {
      if (process.platform === "win32") {
        throw new Error(
          "seekdb 官方暂不支持 Windows 嵌入式模式，请改用 SEEKDB_MODE=server 连接本地 seekdb 服务（或使用 Docker）",
        );
      }
      await fs.mkdir(path.dirname(s.path), { recursive: true });
      client = new SeekdbClient({ path: s.path, database: s.database });
    } else {
      throw new Error(`未知的 SEEKDB_MODE: ${s.mode}`);
    }
    await client.execute("SELECT 1");
    return client;
  }

  schema() {
    return new Schema({
      vectorIndex: new VectorIndexConfig({
        hnsw: {
          dimension: this.cfg.model.dimension,
          distance: "cosine",
          type: "hnsw",
          m: 16,
          ef_construction: 200,
          ef_search: 64,
        },
        embeddingFunction: null,
      }),
      fulltextIndex: new FulltextIndexConfig("ik", { ik_mode: "smart" }),
    });
  }

  async getCollection(name) {
    assertKbName(name);
    if (this.collectionCache.has(name)) return this.collectionCache.get(name);
    const client = await this.connect();
    if (!(await client.hasCollection(name))) {
      const error = new Error(`知识库不存在: ${name}`);
      error.statusCode = 404;
      throw error;
    }
    const collection = await client.getCollection({ name, embeddingFunction: null });
    this.collectionCache.set(name, collection);
    return collection;
  }

  async createKb(name) {
    assertKbName(name);
    const client = await this.connect();
    if (await client.hasCollection(name)) {
      const error = new Error(`知识库已存在: ${name}`);
      error.statusCode = 409;
      throw error;
    }
    const collection = await client.createCollection({ name, schema: this.schema() });
    this.collectionCache.set(name, collection);
    return { name, count: 0, dimension: this.cfg.model.dimension };
  }

  async deleteKb(name) {
    assertKbName(name);
    const client = await this.connect();
    if (await client.hasCollection(name)) {
      await client.deleteCollection(name);
    }
    this.collectionCache.delete(name);
    return { deleted: name };
  }

  async resetKb(name) {
    await this.deleteKb(name);
    return this.createKb(name);
  }

  async listKbs() {
    const client = await this.connect();
    const collections = await client.listCollections({ withEmbeddingFunction: false });
    const result = [];
    for (const collection of collections) {
      const name = collection.name;
      if (!name.startsWith("kb_")) continue;
      try {
        const count = await collection.count();
        result.push({ name, count, dimension: collection.dimension ?? this.cfg.model.dimension });
      } catch {
        result.push({ name, count: null, dimension: collection.dimension ?? this.cfg.model.dimension });
      }
    }
    result.sort((a, b) => a.name.localeCompare(b.name));
    return result;
  }

  async ensureDefaultKb() {
    const client = await this.connect();
    const name = this.cfg.defaultKb;
    if (!(await client.hasCollection(name))) {
      await this.createKb(name);
    }
    return this.getCollection(name);
  }

  async stats(name) {
    const collection = await this.getCollection(name);
    const count = await collection.count();
    let description = null;
    try {
      description = await collection.describe();
    } catch {
      // describe is not essential for the UI
    }
    return {
      name,
      count,
      dimension: description?.dimension ?? this.cfg.model.dimension,
      distance: description?.distance ?? "cosine",
    };
  }

  async addDocuments(name, documents) {
    if (!Array.isArray(documents) || documents.length === 0) {
      const error = new Error("documents 不能为空");
      error.statusCode = 400;
      throw error;
    }
    const collection = await this.getCollection(name);
    const dim = this.cfg.model.dimension;
    const ids = documents.map((d) => String(d.id));
    if (new Set(ids).size !== ids.length) {
      const error = new Error("同一批次存在重复的文档 ID");
      error.statusCode = 400;
      throw error;
    }
    for (const doc of documents) {
      if (!doc.text || typeof doc.text !== "string") {
        const error = new Error("每条文档必须包含非空 text");
        error.statusCode = 400;
        throw error;
      }
      if (!Array.isArray(doc.embedding) || doc.embedding.length !== dim) {
        const error = new Error(`文档 ${doc.id} 的向量维度应为 ${dim}`);
        error.statusCode = 400;
        throw error;
      }
    }

    const startedAt = performance.now();
    let insertMs = 0;
    for (let offset = 0; offset < documents.length; offset += ADD_BATCH_SIZE) {
      const batch = documents.slice(offset, offset + ADD_BATCH_SIZE);
      const t0 = performance.now();
      await collection.upsert({
        ids: batch.map((d) => String(d.id)),
        documents: batch.map((d) => d.text),
        metadatas: batch.map((d) => d.metadata || {}),
        embeddings: batch.map((d) => d.embedding),
      });
      insertMs += performance.now() - t0;
    }

    const refreshStart = performance.now();
    await collection.refresh_index();
    const refreshMs = performance.now() - refreshStart;

    return {
      added: documents.length,
      total: await collection.count(),
      timings: {
        insertMs: Number(insertMs.toFixed(2)),
        refreshMs: Number(refreshMs.toFixed(2)),
        totalMs: Number((performance.now() - startedAt).toFixed(2)),
      },
    };
  }

  async refresh(name) {
    const collection = await this.getCollection(name);
    const t0 = performance.now();
    await collection.refresh_index();
    return { name, refreshMs: Number((performance.now() - t0).toFixed(2)) };
  }

  async listDocuments(name, limit = 200, offset = 0) {
    const collection = await this.getCollection(name);
    const safeLimit = Math.min(500, Math.max(1, Number(limit) || 200));
    const safeOffset = Math.max(0, Number(offset) || 0);
    const result = await collection.get({
      limit: safeLimit,
      offset: safeOffset,
      include: ["documents", "metadatas"],
    });
    return {
      total: await collection.count(),
      limit: safeLimit,
      offset: safeOffset,
      documents: result.ids.map((id, index) => ({
        id,
        text: result.documents?.[index] ?? null,
        metadata: result.metadatas?.[index] ?? null,
      })),
    };
  }

  async search(name, { query, embedding, topK = 10 }) {
    const collection = await this.getCollection(name);
    const dim = this.cfg.model.dimension;
    if (!Array.isArray(embedding) || embedding.length !== dim) {
      const error = new Error(`查询向量维度应为 ${dim}`);
      error.statusCode = 400;
      throw error;
    }
    const safeTopK = normalizeTopK(topK);
    const fulltextQuery = sanitizeFulltextQuery(query);
    const include = ["documents", "metadatas", "distances"];
    const t0 = performance.now();
    let raw;
    let mode = "hybrid";
    try {
      raw = await collection.hybridSearch({
        query: fulltextQuery ? { whereDocument: { $contains: fulltextQuery } } : undefined,
        knn: { queryEmbeddings: [embedding], nResults: Math.max(safeTopK * 4, 20) },
        rank: { rrf: { rankWindowSize: Math.max(safeTopK * 4, 20), rankConstant: 60 } },
        nResults: safeTopK,
        include,
      });
    } catch (error) {
      if (!fulltextQuery) throw error;
      // A malformed full-text expression should not take down retrieval. Fall back to
      // pure vector search and annotate the response so the UI can surface it.
      mode = "vector-fallback";
      raw = await collection.query({
        queryEmbeddings: [embedding],
        nResults: safeTopK,
        include,
      });
    }
    const dbMs = Number((performance.now() - t0).toFixed(2));
    const ids = raw.ids?.[0] || [];
    const documents = raw.documents?.[0] || [];
    const metadatas = raw.metadatas?.[0] || [];
    const distances = raw.distances?.[0] || [];
    const results = ids.map((id, index) => ({
      id,
      text: documents[index] ?? "",
      metadata: metadatas[index] ?? {},
      score: distances[index] == null ? null : Number(distances[index]),
    }));
    return {
      mode,
      query,
      topK: safeTopK,
      results,
      timings: { dbMs, totalMs: Number((performance.now() - t0).toFixed(2)) },
    };
  }

  async close() {
    if (this.client) {
      await this.client.close();
      this.client = null;
      this.collectionCache.clear();
    }
  }
}
