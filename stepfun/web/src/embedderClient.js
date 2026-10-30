/**
 * Thin promise wrapper around the embedding Web Worker.
 * The worker is created lazily so import/search can share one model instance.
 */
export class EmbedderClient {
  constructor() {
    this.worker = null;
    this.pending = new Map();
    this.nextId = 1;
    this.listeners = new Set();
    this.status = { state: "idle", backend: null, dtype: null, loadMs: null, webgpuReason: "" };
  }

  #ensureWorker() {
    if (this.worker) return this.worker;
    this.worker = new Worker(new URL("./embedder.worker.js", import.meta.url), { type: "module" });
    this.worker.addEventListener("message", (event) => this.#handleMessage(event.data));
    this.worker.addEventListener("error", (event) => {
      const message = event.message || "Embedding Worker 发生未知错误";
      for (const pending of this.pending.values()) {
        pending.reject(new Error(message));
      }
      this.pending.clear();
      this.#emit({ type: "worker-error", message });
    });
    return this.worker;
  }

  #handleMessage(data) {
    if (!data || data.type === "worker-ready") return;
    if (data.type === "fetch-debug") {
      const log = (globalThis.__stepfunFetchLog ||= []);
      log.push(data);
      if (log.length > 200) log.shift();
      return;
    }
    if (data.type === "model-progress" || data.type === "backend-attempt" || data.type === "backend-failed") {
      this.#emit(data);
      return;
    }
    const pending = this.pending.get(data.requestId);
    if (!pending) return;
    if (data.type.endsWith("-progress")) {
      pending.onProgress?.(data);
      return;
    }
    if (data.type.endsWith("-result")) {
      this.pending.delete(data.requestId);
      if (data.type === "init-result") {
        this.status = {
          state: "ready",
          backend: data.backend,
          dtype: data.dtype,
          loadMs: data.loadMs,
          webgpuReason: data.webgpuReason || "",
        };
      }
      pending.resolve(data);
      return;
    }
    if (data.type.endsWith("-error")) {
      this.pending.delete(data.requestId);
      pending.reject(new Error(data.message || "Embedding 失败"));
    }
  }

  #emit(event) {
    for (const listener of this.listeners) listener(event);
  }

  onEvent(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  #request(message, onProgress, transfer = []) {
    const worker = this.#ensureWorker();
    const requestId = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(requestId, { resolve, reject, onProgress });
      worker.postMessage({ ...message, requestId }, transfer);
    });
  }

  init(backend = "auto", onProgress) {
    return this.#request({ type: "init", backend }, onProgress);
  }

  embed(texts, { batchSize = 8, onProgress } = {}) {
    const plain = Array.isArray(texts) ? texts : [texts];
    return this.#request({ type: "embed", texts: plain, batchSize }, onProgress);
  }

  dispose() {
    if (this.worker) {
      this.worker.terminate();
      this.worker = null;
    }
  }
}

export function vectorToArray(vector) {
  if (!vector) return [];
  if (Array.isArray(vector)) return vector;
  return Array.from(vector, (value) => Number(Number(value).toFixed(7)));
}
