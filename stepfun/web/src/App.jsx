import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { EmbedderClient, vectorToArray } from "./embedderClient";
import { SAMPLE_CORPUS, SAMPLE_QUERIES } from "./sampleCorpus";
import { buildFileChunks, buildSampleChunks, readTextFile } from "./chunking";

const STORAGE_KEY = "stepfun.activeKb";
const IMPORT_BATCH = 32;

function formatMs(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  const ms = Number(value);
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)} s`;
  return `${ms.toFixed(ms < 10 ? 2 : 1)} ms`;
}

function percentile(values, p) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const index = Math.min(sorted.length - 1, Math.max(0, Math.ceil((p / 100) * sorted.length) - 1));
  return Number(sorted[index].toFixed(2));
}

function mean(values) {
  if (!values.length) return null;
  return Number((values.reduce((sum, value) => sum + value, 0) / values.length).toFixed(2));
}

function Highlight({ text, query }) {
  const parts = useMemo(() => {
    const source = String(text || "");
    const terms = new Set();
    const trimmed = String(query || "").trim();
    if (trimmed) terms.add(trimmed);
    for (const token of trimmed.split(/[\s，。！？、；：,.;:!?]+/)) {
      if (token.length >= 2) terms.add(token);
    }
    const unique = [...terms].filter(Boolean).sort((a, b) => b.length - a.length);
    if (!unique.length) return [source];
    const escaped = unique.map((term) => term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    return source.split(new RegExp(`(${escaped.join("|")})`, "gi"));
  }, [text, query]);
  const termSet = new Set(
    String(query || "")
      .split(/[\s，。！？、；：,.;:!?]+/)
      .filter((term) => term.length >= 2)
      .map((term) => term.toLowerCase()),
  );
  return parts.map((part, index) =>
    termSet.has(part.toLowerCase()) || part === query ? <mark key={index}>{part}</mark> : <span key={index}>{part}</span>,
  );
}

function Chip({ tone = "neutral", children, title }) {
  return <span className={`chip chip-${tone}`} title={title}>{children}</span>;
}

function Sparkline({ values }) {
  if (!values?.length) return <div className="spark-empty">暂无数据</div>;
  const width = 220;
  const height = 52;
  const max = Math.max(...values, 1);
  const points = values
    .map((value, index) => `${(index / Math.max(values.length - 1, 1)) * width},${height - (value / max) * (height - 8) - 4}`)
    .join(" ");
  return (
    <svg className="sparkline" viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth="2" />
    </svg>
  );
}

export default function App() {
  const embedderRef = useRef(null);
  const [health, setHealth] = useState(null);
  const [kbs, setKbs] = useState([]);
  const [activeKb, setActiveKb] = useState(() => localStorage.getItem(STORAGE_KEY) || "kb_stepfun_demo");
  const [kbStats, setKbStats] = useState(null);
  const [documents, setDocuments] = useState([]);
  const [embedderStatus, setEmbedderStatus] = useState({
    state: "idle",
    backend: null,
    dtype: null,
    loadMs: null,
    webgpuReason: "",
  });
  const [modelProgress, setModelProgress] = useState(null);
  const [initFailures, setInitFailures] = useState([]);
  const [drafts, setDrafts] = useState([]);
  const [fileNotes, setFileNotes] = useState([]);
  const [importing, setImporting] = useState(false);
  const [importProgress, setImportProgress] = useState(null);
  const [importResult, setImportResult] = useState(null);
  const [resetBeforeImport, setResetBeforeImport] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [searchMetrics, setSearchMetrics] = useState(null);
  const [searchHistory, setSearchHistory] = useState([]);
  const [benchmark, setBenchmark] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem("stepfun.benchmark") || "null");
    } catch {
      return null;
    }
  });
  const [benchmarking, setBenchmarking] = useState(false);
  const [newKbName, setNewKbName] = useState("");
  const [showNewKb, setShowNewKb] = useState(false);
  const [toast, setToast] = useState(null);
  const [dragActive, setDragActive] = useState(false);

  useEffect(() => {
    const client = new EmbedderClient();
    embedderRef.current = client;
    const unsubscribe = client.onEvent((event) => {
      if (event.type === "model-progress") {
        setModelProgress({
          file: event.file,
          progress: event.progress,
          loaded: event.loaded,
          total: event.total,
          backend: event.backend,
        });
      } else if (event.type === "backend-attempt") {
        setEmbedderStatus((previous) => ({
          ...previous,
          state: "loading",
          backend: event.backend,
          dtype: event.dtype,
        }));
      } else if (event.type === "backend-failed") {
        setInitFailures((previous) => [...previous, `${event.backend}: ${event.message}`]);
      }
    });
    void bootstrap();
    return () => {
      unsubscribe();
      client.dispose();
    };
  }, []);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, activeKb);
  }, [activeKb]);

  useEffect(() => {
    if (!toast) return undefined;
    const timer = setTimeout(() => setToast(null), 4200);
    return () => clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    // A small automation/testing surface used by the benchmark and E2E scripts.
    window.__stepfun = {
      state: () => ({
        activeKb,
        kbStats,
        drafts: drafts.length,
        results: results.length,
        embedder: embedderStatus,
        benchmark,
      }),
      loadSample,
      importSample: async () => {
        loadSample();
        return importDocuments({ overrideDrafts: buildSampleChunks(SAMPLE_CORPUS) });
      },
      search: (text, topK = 5) => runSearchText(text, topK),
      benchmark: () => runBenchmark(),
    };
  });

  async function bootstrap() {
    try {
      const [healthPayload, kbPayload] = await Promise.all([api.health(), api.listKbs()]);
      setHealth(healthPayload);
      setKbs(kbPayload.kbs);
      const stored = localStorage.getItem(STORAGE_KEY);
      const target =
        kbPayload.kbs.find((item) => item.name === stored)?.name ||
        kbPayload.kbs[0]?.name ||
        healthPayload.defaultKb;
      await loadKb(target);
      if (healthPayload.ok) {
        void ensureModel("auto").catch((error) => {
          setEmbedderStatus((previous) => ({ ...previous, state: "error", error: error.message }));
        });
      }
    } catch (error) {
      setToast({ type: "error", text: error.message });
    }
  }

  async function loadKb(name) {
    setActiveKb(name);
    try {
      const [stats, docs] = await Promise.all([api.stats(name), api.documents(name)]);
      setKbStats(stats);
      setDocuments(docs.documents || []);
    } catch (error) {
      setToast({ type: "error", text: error.message });
    }
  }

  async function refreshKbList() {
    try {
      const payload = await api.listKbs();
      setKbs(payload.kbs);
    } catch {
      // Keep the current list if a refresh races with a database operation.
    }
  }

  async function ensureModel(forceBackend = "auto") {
    const client = embedderRef.current;
    if (!client) throw new Error("嵌入器尚未就绪");
    if (client.status.state === "ready" && (forceBackend === "auto" || client.status.backend === forceBackend)) {
      setEmbedderStatus(client.status);
      return client.status;
    }
    setInitFailures([]);
    setModelProgress(null);
    setEmbedderStatus((previous) => ({ ...previous, state: "loading" }));
    const result = await client.init(forceBackend, (event) => {
      if (event.type === "model-progress") return;
      if (event.type === "backend-attempt") {
        setEmbedderStatus((previous) => ({
          ...previous,
          state: "loading",
          backend: event.backend,
          dtype: event.dtype,
        }));
      }
    });
    setEmbedderStatus({
      state: "ready",
      backend: result.backend,
      dtype: result.dtype,
      loadMs: result.loadMs,
      webgpuReason: result.webgpuReason || "",
    });
    return result;
  }

  async function handleFiles(fileList) {
    const incoming = [];
    const notes = [];
    for (const file of Array.from(fileList)) {
      try {
        const text = await readTextFile(file);
        const chunks = buildFileChunks(file.name, text);
        if (!chunks.length) throw new Error("没有可导入的文本内容");
        incoming.push(...chunks);
        notes.push({ name: file.name, chunks: chunks.length });
      } catch (error) {
        setToast({ type: "error", text: `${file.name}: ${error.message}` });
      }
    }
    setDrafts((previous) => {
      const merged = new Map(previous.map((item) => [item.id, item]));
      for (const item of incoming) merged.set(item.id, item);
      return [...merged.values()];
    });
    setFileNotes((previous) => [...previous, ...notes]);
  }

  function loadSample() {
    const chunks = buildSampleChunks(SAMPLE_CORPUS);
    setDrafts(chunks);
    setFileNotes([{ name: `内置示例语料 · ${SAMPLE_CORPUS.length} 篇`, chunks: chunks.length }]);
    setImportResult(null);
    setToast({ type: "info", text: `已准备 ${chunks.length} 个示例片段` });
  }

  function clearDrafts() {
    setDrafts([]);
    setFileNotes([]);
  }

  async function importDocuments(options = {}) {
    const sourceDrafts = options.overrideDrafts || drafts;
    if (!sourceDrafts.length) {
      setToast({ type: "error", text: "请先选择文件或加载示例语料" });
      return null;
    }
    setImporting(true);
    setImportResult(null);
    try {
      setImportProgress({ phase: "model", done: 0, total: sourceDrafts.length, label: "检查端侧模型" });
      await ensureModel("auto");

      if (resetBeforeImport && !options.overrideDrafts) {
        setImportProgress({ phase: "reset", done: 0, total: sourceDrafts.length, label: "重建知识库" });
        await api.resetKb(activeKb);
      }

      setImportProgress({ phase: "embedding", done: 0, total: sourceDrafts.length, label: "浏览器本地向量化" });
      const embeddingResult = await embedderRef.current.embed(
        sourceDrafts.map((item) => item.text),
        {
          batchSize: 8,
          onProgress: (progress) => {
            setImportProgress({
              phase: "embedding",
              done: progress.done,
              total: progress.total,
              label: "浏览器本地向量化",
              batchMs: progress.batchMs,
            });
          },
        },
      );

      const documentsPayload = sourceDrafts.map((item, index) => ({
        id: item.id,
        text: item.text,
        metadata: item.metadata,
        embedding: vectorToArray(embeddingResult.embeddings[index]),
      }));

      setImportProgress({ phase: "writing", done: 0, total: documentsPayload.length, label: "写入 seekdb 并刷新索引" });
      let added = 0;
      let insertMs = 0;
      let refreshMs = 0;
      for (let offset = 0; offset < documentsPayload.length; offset += IMPORT_BATCH) {
        const batch = documentsPayload.slice(offset, offset + IMPORT_BATCH);
        const response = await api.addDocuments(activeKb, batch);
        added += response.added;
        insertMs += response.timings.insertMs;
        refreshMs += response.timings.refreshMs;
        setImportProgress({
          phase: "writing",
          done: Math.min(offset + IMPORT_BATCH, documentsPayload.length),
          total: documentsPayload.length,
          label: "写入 seekdb 并刷新索引",
        });
      }

      const result = {
        added,
        embedMs: embeddingResult.elapsedMs,
        insertMs: Number(insertMs.toFixed(2)),
        refreshMs: Number(refreshMs.toFixed(2)),
        backend: embeddingResult.backend,
        dtype: embeddingResult.dtype,
        at: new Date().toISOString(),
      };
      setImportResult(result);
      setDrafts([]);
      setFileNotes([]);
      await refreshKbList();
      await loadKb(activeKb);
      setToast({ type: "success", text: `已导入 ${added} 个片段，索引已刷新` });
      return result;
    } catch (error) {
      setToast({ type: "error", text: error.message });
      return null;
    } finally {
      setImporting(false);
      setImportProgress(null);
    }
  }

  async function runSearchText(text, topK = 10) {
    const trimmed = String(text || "").trim();
    if (!trimmed) return null;
    setQuery(trimmed);
    setSearching(true);
    try {
      const startedAt = performance.now();
      await ensureModel("auto");
      const embeddingResult = await embedderRef.current.embed([trimmed], { batchSize: 1 });
      const embedding = vectorToArray(embeddingResult.embeddings[0]);
      const response = await api.search(activeKb, { query: trimmed, embedding, topK });
      const endToEndMs = performance.now() - startedAt;
      setResults(response.results);
      const metrics = {
        embedMs: embeddingResult.elapsedMs,
        dbMs: response.timings.dbMs,
        totalMs: Number(endToEndMs.toFixed(2)),
        mode: response.mode,
        topK,
        query: trimmed,
        at: new Date().toISOString(),
      };
      setSearchMetrics(metrics);
      setSearchHistory((previous) => [...previous.slice(-19), metrics]);
      return response;
    } catch (error) {
      setToast({ type: "error", text: error.message });
      return null;
    } finally {
      setSearching(false);
    }
  }

  async function handleSearch(event) {
    event.preventDefault();
    await runSearchText(query, 10);
  }

  async function handleCreateKb(event) {
    event.preventDefault();
    try {
      const payload = await api.createKb(newKbName.trim());
      setNewKbName("");
      setShowNewKb(false);
      await refreshKbList();
      await loadKb(payload.name);
      setToast({ type: "success", text: `已创建 ${payload.name}` });
    } catch (error) {
      setToast({ type: "error", text: error.message });
    }
  }

  async function handleDeleteKb(name) {
    if (!window.confirm(`删除知识库 ${name}？其中的向量和原文将一并删除。`)) return;
    try {
      await api.deleteKb(name);
      await refreshKbList();
      const payload = await api.listKbs();
      const next = payload.kbs.find((item) => item.name !== name)?.name;
      if (next) await loadKb(next);
      setToast({ type: "success", text: `已删除 ${name}` });
    } catch (error) {
      setToast({ type: "error", text: error.message });
    }
  }

  async function handleResetKb() {
    if (!window.confirm(`清空知识库 ${activeKb}？`)) return;
    try {
      await api.resetKb(activeKb);
      setResults([]);
      setSearchMetrics(null);
      await loadKb(activeKb);
      await refreshKbList();
      setToast({ type: "success", text: "知识库已清空" });
    } catch (error) {
      setToast({ type: "error", text: error.message });
    }
  }

  async function runBenchmark() {
    if (!kbStats?.count) {
      setToast({ type: "error", text: "请先导入示例语料，再运行性能基准" });
      return null;
    }
    setBenchmarking(true);
    try {
      await ensureModel("auto");
      const texts = SAMPLE_CORPUS.map((item) => `${item.title}\n${item.text}`);
      const embeddingStart = performance.now();
      const embeddingResult = await embedderRef.current.embed(texts, { batchSize: 8 });
      const embeddingMs = performance.now() - embeddingStart;

      const queries = SAMPLE_QUERIES.slice(0, 20);
      const queryEmbedding = await embedderRef.current.embed(queries, { batchSize: 8 });
      // One warm-up search loads the vector index pages into the DB cache; mixing
      // that first-touch cost into the percentile would overstate steady state.
      await api.search(activeKb, {
        query: queries[0],
        embedding: vectorToArray(queryEmbedding.embeddings[0]),
        topK: 5,
      });
      const dbTimes = [];
      for (let index = 0; index < queries.length; index += 1) {
        const response = await api.search(activeKb, {
          query: queries[index],
          embedding: vectorToArray(queryEmbedding.embeddings[index]),
          topK: 5,
        });
        dbTimes.push(response.timings.dbMs);
      }

      // True end-to-end: one query at a time, including browser embedding and
      // the HTTP round-trip to seekdb. Ten queries are enough for a stable median.
      const e2eQueries = queries.slice(0, 10);
      const endToEndTimes = [];
      const queryEmbedTimes = [];
      for (const text of e2eQueries) {
        const startedAt = performance.now();
        const embedded = await embedderRef.current.embed([text], { batchSize: 1 });
        queryEmbedTimes.push(embedded.elapsedMs);
        await api.search(activeKb, {
          query: text,
          embedding: vectorToArray(embedded.embeddings[0]),
          topK: 5,
        });
        endToEndTimes.push(performance.now() - startedAt);
      }

      const result = {
        at: new Date().toISOString(),
        model: {
          id: health?.model?.id || "bge-small-zh-v1.5",
          backend: embedderStatus.backend,
          dtype: embedderStatus.dtype,
          loadMs: embedderStatus.loadMs,
        },
        embedding: {
          texts: texts.length,
          totalMs: Number(embeddingMs.toFixed(2)),
          perTextMs: Number((embeddingMs / texts.length).toFixed(2)),
          textsPerSecond: Number((texts.length / (embeddingMs / 1000)).toFixed(2)),
          batchMs: embeddingResult.batchMs,
        },
        search: {
          queries: queries.length,
          dbP50Ms: percentile(dbTimes, 50),
          dbP95Ms: percentile(dbTimes, 95),
          dbMeanMs: mean(dbTimes),
          queryEmbedP50Ms: percentile(queryEmbedTimes, 50),
          e2eQueries: e2eQueries.length,
          e2eP50Ms: percentile(endToEndTimes, 50),
          e2eP95Ms: percentile(endToEndTimes, 95),
          rawDbMs: dbTimes,
          rawE2eMs: endToEndTimes,
        },
        kb: { name: activeKb, count: kbStats?.count || null },
      };
      setBenchmark(result);
      localStorage.setItem("stepfun.benchmark", JSON.stringify(result));
      window.__stepfunBenchmark = result;
      setToast({ type: "success", text: "性能基准完成" });
      return result;
    } catch (error) {
      setToast({ type: "error", text: error.message });
      return null;
    } finally {
      setBenchmarking(false);
    }
  }

  async function handleBackendChange(backend) {
    try {
      await ensureModel(backend);
      setToast({ type: "info", text: `推理后端已切换为 ${backend === "wasm" ? "WASM / INT8" : "WebGPU / FP16"}` });
    } catch (error) {
      if (backend === "webgpu") {
        try {
          await ensureModel("wasm");
          setToast({ type: "info", text: "WebGPU 不可用，已自动降级为 WASM / INT8" });
          return;
        } catch {
          // Report the original WebGPU failure below.
        }
      }
      setToast({ type: "error", text: error.message });
    }
  }

  const totalDraftChars = useMemo(() => drafts.reduce((sum, item) => sum + item.text.length, 0), [drafts]);
  const backendLabel = embedderStatus.backend === "webgpu" ? "WebGPU" : embedderStatus.backend === "wasm" ? "WASM" : "未加载";
  const precisionLabel = embedderStatus.dtype === "fp16" ? "FP16" : embedderStatus.dtype === "q8" ? "INT8" : "—";
  const connected = Boolean(health?.seekdb?.connected);
  const recentDbTimes = searchHistory.map((item) => item.dbMs).filter((value) => typeof value === "number");

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">S</div>
          <div>
            <div className="brand-name">StepKB</div>
            <div className="brand-sub">端侧向量知识库</div>
          </div>
        </div>

        <div className="sidebar-section-head">
          <span>知识库</span>
          <button className="icon-button" onClick={() => setShowNewKb((value) => !value)} title="新建知识库">＋</button>
        </div>
        {showNewKb && (
          <form className="new-kb-form" onSubmit={handleCreateKb}>
            <input
              value={newKbName}
              onChange={(event) => setNewKbName(event.target.value)}
              placeholder="名称，例如 notes"
              autoFocus
            />
            <button type="submit">创建</button>
          </form>
        )}
        <div className="kb-list">
          {kbs.map((item) => (
            <button
              key={item.name}
              className={`kb-item ${item.name === activeKb ? "active" : ""}`}
              onClick={() => loadKb(item.name)}
            >
              <span className="kb-icon">▦</span>
              <span className="kb-meta">
                <span className="kb-name">{item.name.replace(/^kb_/, "")}</span>
                <span className="kb-count">{item.count ?? "—"} 片段</span>
              </span>
            </button>
          ))}
          {!kbs.length && <div className="sidebar-empty">暂无知识库</div>}
        </div>

        <div className="sidebar-foot">
          <div className="foot-row"><span>模型</span><b>{health?.model?.id || "bge-small-zh-v1.5"}</b></div>
          <div className="foot-row"><span>维度</span><b>{health?.model?.dimension || 512} dim</b></div>
          <div className="foot-row"><span>引擎</span><b>seekdb {health?.seekdb?.mode || "server"}</b></div>
          <div className="foot-note">向量与原文只写入本机 seekdb；推理在浏览器内完成。</div>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <div className="eyebrow">STEPFUN · OCEANBASE 2026</div>
            <h1>端侧 AI 推理 × seekdb 混合检索</h1>
            <p className="subtitle">
              文档在浏览器本地向量化，向量与原文写入 seekdb，查询通过数据库原生混合检索返回。
            </p>
          </div>
          <div className="status-cluster">
            <Chip tone={connected ? "green" : "red"} title={health?.seekdb?.error || ""}>
              <span className="dot" /> seekdb {connected ? "已连接" : "未连接"}
            </Chip>
            <Chip tone={embedderStatus.state === "ready" ? "blue" : embedderStatus.state === "error" ? "red" : "amber"}>
              {embedderStatus.state === "loading" ? "模型加载中" : `${backendLabel} · ${precisionLabel}`}
            </Chip>
          </div>
        </header>

        <section className="stat-strip">
          <div className="stat-card">
            <span className="stat-label">当前知识库</span>
            <strong>{activeKb.replace(/^kb_/, "")}</strong>
            <span className="stat-sub">{kbStats?.count ?? 0} 个片段 · {documents.length} 条记录已载入视图</span>
          </div>
          <div className="stat-card">
            <span className="stat-label">推理后端</span>
            <strong>{embedderStatus.state === "ready" ? `${backendLabel} / ${precisionLabel}` : "等待初始化"}</strong>
            <span className="stat-sub">
              {embedderStatus.loadMs ? `模型加载 ${formatMs(embedderStatus.loadMs)}` : embedderStatus.webgpuReason || "优先 WebGPU，失败自动降级"}
            </span>
          </div>
          <div className="stat-card">
            <span className="stat-label">最近一次检索</span>
            <strong>{searchMetrics ? formatMs(searchMetrics.totalMs) : "—"}</strong>
            <span className="stat-sub">
              {searchMetrics ? `向量化 ${formatMs(searchMetrics.embedMs)} · seekdb ${formatMs(searchMetrics.dbMs)}` : "提交查询后显示分阶段耗时"}
            </span>
          </div>
          <div className="stat-card">
            <span className="stat-label">索引状态</span>
            <strong>{importResult ? "已刷新" : "就绪"}</strong>
            <span className="stat-sub">{importResult ? `上次导入刷新 ${formatMs(importResult.refreshMs)}` : "写入后自动 refresh_index"}</span>
          </div>
        </section>

        <div className="content-grid">
          <div className="column">
            <section className="card search-card">
              <div className="card-head">
                <div>
                  <div className="card-kicker">HYBRID RETRIEVAL</div>
                  <h2>检索知识库</h2>
                </div>
                <div className="card-head-meta">
                  <span className="mono">{kbStats?.count ?? 0} chunks</span>
                </div>
              </div>
              <form className="search-bar" onSubmit={handleSearch}>
                <span className="search-icon" aria-hidden="true">⌕</span>
                <input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="问点什么，例如：seekdb 的混合检索是怎么做的？"
                  aria-label="检索查询"
                />
                <button type="submit" disabled={searching || !query.trim()}>
                  {searching ? "检索中…" : "混合检索"}
                </button>
              </form>
              <div className="search-meta-row">
                <span>向量 + 全文 · RRF 融合 · 数据库内完成</span>
                {searchMetrics && (
                  <span className={`mode-pill ${searchMetrics.mode === "hybrid" ? "ok" : "warn"}`}>
                    {searchMetrics.mode === "hybrid" ? "hybridSearch" : "vector fallback"}
                  </span>
                )}
              </div>

              {results.length > 0 && (
                <div className="result-list">
                  {results.map((result, index) => (
                    <article className="result-item" key={result.id}>
                      <div className="result-rank">{String(index + 1).padStart(2, "0")}</div>
                      <div className="result-body">
                        <div className="result-head">
                          <strong>{result.metadata?.title || result.metadata?.source || result.id}</strong>
                          <span className="score">{result.score == null ? "—" : result.score.toFixed(4)}</span>
                        </div>
                        <p><Highlight text={result.text} query={searchMetrics?.query || query} /></p>
                        <div className="result-tags">
                          <span>{result.metadata?.source || "未知来源"}</span>
                          {result.metadata?.category && <span>{result.metadata.category}</span>}
                          {result.metadata?.chunkIndex != null && (
                            <span>chunk {Number(result.metadata.chunkIndex) + 1}/{result.metadata.chunkCount || "?"}</span>
                          )}
                        </div>
                      </div>
                    </article>
                  ))}
                </div>
              )}
              {!results.length && (
                <div className="empty-state">
                  <div className="empty-glyph">⌕</div>
                  <p>导入语料后，输入自然语言问题。查询向量在浏览器内生成，seekdb 同时执行向量与全文召回，再用 RRF 融合排序。</p>
                </div>
              )}
            </section>

            <section className="card import-card">
              <div className="card-head">
                <div>
                  <div className="card-kicker">LOCAL INGESTION</div>
                  <h2>导入语料</h2>
                </div>
                <div className="card-head-actions">
                  <button className="ghost-button" onClick={loadSample} disabled={importing}>加载示例语料</button>
                  {drafts.length > 0 && <button className="ghost-button danger" onClick={clearDrafts} disabled={importing}>清空待导入</button>}
                </div>
              </div>

              <label
                className={`dropzone ${dragActive ? "dragging" : ""}`}
                onDragOver={(event) => { event.preventDefault(); setDragActive(true); }}
                onDragLeave={() => setDragActive(false)}
                onDrop={(event) => {
                  event.preventDefault();
                  setDragActive(false);
                  void handleFiles(event.dataTransfer.files);
                }}
              >
                <input
                  type="file"
                  multiple
                  accept=".txt,.md,.markdown,.csv,.jsonl,.json,.log,text/plain"
                  onChange={(event) => { void handleFiles(event.target.files); event.target.value = ""; }}
                />
                <span className="drop-icon">↥</span>
                <span className="drop-title">拖入文本文件，或点击选择</span>
                <span className="drop-sub">支持 .txt / .md / .csv / .jsonl · 单文件不超过 8 MB</span>
              </label>

              {fileNotes.length > 0 && (
                <div className="file-list">
                  {fileNotes.map((note, index) => (
                    <div className="file-row" key={`${note.name}-${index}`}>
                      <span className="file-name">{note.name}</span>
                      <span className="file-chunks">{note.chunks} 个片段</span>
                    </div>
                  ))}
                </div>
              )}

              <div className="import-summary">
                <div>
                  <span className="stat-label">待导入</span>
                  <strong>{drafts.length} 片段</strong>
                  <span className="stat-sub">{totalDraftChars.toLocaleString()} 字符</span>
                </div>
                <label className="check-row">
                  <input
                    type="checkbox"
                    checked={resetBeforeImport}
                    onChange={(event) => setResetBeforeImport(event.target.checked)}
                    disabled={importing}
                  />
                  导入前清空当前知识库
                </label>
                <button className="primary-button" onClick={() => importDocuments()} disabled={importing || !drafts.length}>
                  {importing ? "导入中…" : "开始导入"}
                </button>
              </div>

              {importProgress && (
                <div className="progress-block">
                  <div className="progress-head">
                    <span>{importProgress.label}</span>
                    <span className="mono">{importProgress.done}/{importProgress.total}</span>
                  </div>
                  <div className="progress-track">
                    <div
                      className="progress-fill"
                      style={{ width: `${importProgress.total ? Math.round((importProgress.done / importProgress.total) * 100) : 5}%` }}
                    />
                  </div>
                </div>
              )}

              {importResult && (
                <div className="import-result">
                  <div className="import-result-title">本次导入完成</div>
                  <div className="metric-grid">
                    <div><span>片段</span><b>{importResult.added}</b></div>
                    <div><span>本地向量化</span><b>{formatMs(importResult.embedMs)}</b></div>
                    <div><span>写入 seekdb</span><b>{formatMs(importResult.insertMs)}</b></div>
                    <div><span>索引刷新</span><b>{formatMs(importResult.refreshMs)}</b></div>
                  </div>
                  <div className="muted-note">量化精度：{importResult.dtype === "fp16" ? "FP16" : "INT8"} · 后端：{importResult.backend === "webgpu" ? "WebGPU" : "WASM"}</div>
                </div>
              )}
            </section>
          </div>

          <aside className="column side-column">
            <section className="card runtime-card">
              <div className="card-head">
                <div>
                  <div className="card-kicker">RUNTIME</div>
                  <h2>端侧推理</h2>
                </div>
                <Chip tone={embedderStatus.state === "ready" ? "green" : "amber"}>
                  {embedderStatus.state === "ready" ? "在线" : embedderStatus.state === "loading" ? "加载中" : "待命"}
                </Chip>
              </div>
              <div className="runtime-line">
                <span className="runtime-label">模型</span>
                <span className="runtime-value">{health?.model?.id || "bge-small-zh-v1.5"}</span>
              </div>
              <div className="runtime-line">
                <span className="runtime-label">输出维度</span>
                <span className="runtime-value mono">{health?.model?.dimension || 512} dim</span>
              </div>
              <div className="runtime-line">
                <span className="runtime-label">后端</span>
                <span className="runtime-value">{backendLabel} / {precisionLabel}</span>
              </div>
              <div className="runtime-line">
                <span className="runtime-label">模型加载</span>
                <span className="runtime-value mono">{embedderStatus.loadMs ? formatMs(embedderStatus.loadMs) : "—"}</span>
              </div>
              {modelProgress && embedderStatus.state === "loading" && (
                <div className="mini-progress">
                  <div className="mini-progress-label">{modelProgress.file || "模型文件"} · {modelProgress.progress || 0}%</div>
                  <div className="progress-track small"><div className="progress-fill" style={{ width: `${modelProgress.progress || 2}%` }} /></div>
                </div>
              )}
              <div className="backend-switch">
                <button className={embedderStatus.backend === "webgpu" ? "active" : ""} onClick={() => handleBackendChange("webgpu")} disabled={embedderStatus.state === "loading"}>WebGPU / FP16</button>
                <button className={embedderStatus.backend === "wasm" ? "active" : ""} onClick={() => handleBackendChange("wasm")} disabled={embedderStatus.state === "loading"}>WASM / INT8</button>
              </div>
              {embedderStatus.webgpuReason && (
                <p className="muted-note">WebGPU 不可用原因：{embedderStatus.webgpuReason}</p>
              )}
              {initFailures.length > 0 && (
                <p className="muted-note danger-text">初始化失败：{initFailures.join("；")}</p>
              )}
            </section>

            <section className="card quant-card">
              <div className="card-head">
                <div>
                  <div className="card-kicker">QUANTIZATION</div>
                  <h2>模型体积</h2>
                </div>
                <span className="mono muted">INT8 / FP16</span>
              </div>
              <div className="size-table">
                <div className="size-row head"><span>精度</span><span>体积</span><span>压缩比</span></div>
                <div className="size-row"><span>FP32 基线</span><span>{health?.model?.files?.fp32?.mib ? `${health.model.files.fp32.mib} MB` : "—"}</span><span>1.00×</span></div>
                <div className="size-row"><span>FP16</span><span>{health?.model?.files?.fp16?.mib ? `${health.model.files.fp16.mib} MB` : "—"}</span><span>{health?.model?.compression?.fp16 ? `${health.model.compression.fp16}×` : "—"}</span></div>
                <div className="size-row"><span>INT8</span><span>{health?.model?.files?.int8?.mib ? `${health.model.files.int8.mib} MB` : "—"}</span><span>{health?.model?.compression?.int8 ? `${health.model.compression.int8}×` : "—"}</span></div>
              </div>
              <p className="muted-note">WebGPU 使用 FP16 权重；WASM 使用 INT8 动态量化权重。质量对比见技术说明。</p>
            </section>

            <section className="card metrics-card">
              <div className="card-head">
                <div>
                  <div className="card-kicker">LATENCY</div>
                  <h2>检索延迟</h2>
                </div>
                <span className="mono muted">recent 20</span>
              </div>
              <Sparkline values={recentDbTimes} />
              <div className="metric-grid">
                <div><span>向量化</span><b>{searchMetrics ? formatMs(searchMetrics.embedMs) : "—"}</b></div>
                <div><span>seekdb</span><b>{searchMetrics ? formatMs(searchMetrics.dbMs) : "—"}</b></div>
                <div><span>端到端</span><b>{searchMetrics ? formatMs(searchMetrics.totalMs) : "—"}</b></div>
                <div><span>模式</span><b>{searchMetrics?.mode === "hybrid" ? "混合" : searchMetrics ? "向量" : "—"}</b></div>
              </div>
              <button className="primary-button wide" onClick={runBenchmark} disabled={benchmarking || !kbStats?.count}>
                {benchmarking ? "基准测试运行中…" : "运行性能基准"}
              </button>
              {benchmark && (
                <div className="benchmark-result">
                  <div className="benchmark-head"><span>最近基准</span><span>{new Date(benchmark.at).toLocaleString()}</span></div>
                  <div className="metric-grid">
                    <div><span>Embedding</span><b>{benchmark.embedding.textsPerSecond} 条/s</b></div>
                    <div><span>每条约</span><b>{benchmark.embedding.perTextMs} ms</b></div>
                    <div><span>seekdb P50</span><b>{benchmark.search.dbP50Ms} ms</b></div>
                    <div><span>seekdb P95</span><b>{benchmark.search.dbP95Ms} ms</b></div>
                    <div><span>端到端 P50</span><b>{benchmark.search.e2eP50Ms} ms</b></div>
                    <div><span>端到端 P95</span><b>{benchmark.search.e2eP95Ms} ms</b></div>
                  </div>
                </div>
              )}
            </section>

            <section className="card kb-admin-card">
              <div className="card-kicker">COLLECTION</div>
              <div className="kb-admin-row">
                <div>
                  <strong>{activeKb}</strong>
                  <span className="muted-note">{kbStats?.count ?? 0} 片段 · {kbStats?.dimension || 512} 维 · {kbStats?.distance || "cosine"}</span>
                </div>
                <div className="kb-admin-actions">
                  <button className="ghost-button" onClick={() => loadKb(activeKb)}>刷新</button>
                  <button className="ghost-button danger" onClick={handleResetKb}>清空</button>
                  <button className="ghost-button danger" onClick={() => handleDeleteKb(activeKb)}>删除</button>
                </div>
              </div>
            </section>
          </aside>
        </div>
      </main>

      {toast && <div className={`toast toast-${toast.type}`}>{toast.text}</div>}
    </div>
  );
}
