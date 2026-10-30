import "./fetchDebug.js";
import { env, pipeline } from "@huggingface/transformers";

const MODEL_ID = "bge-small-zh-v1.5";
const MODEL_DIM = 512;

env.allowLocalModels = true;
env.allowRemoteModels = false;
env.useBrowserCache = false;
env.localModelPath = new URL("/models/", self.location.origin).href;
env.backends.onnx.wasm.wasmPaths = "/ort/";
env.backends.onnx.wasm.numThreads = 1;

let extractor = null;
let activeBackend = null;
let activeDtype = null;
let loadMs = 0;

function post(message, transfer = []) {
  self.postMessage(message, transfer);
}

async function detectWebGPU() {
  if (!("gpu" in navigator)) return { available: false, reason: "当前浏览器未暴露 navigator.gpu" };
  try {
    const adapter = await navigator.gpu.requestAdapter();
    if (!adapter) return { available: false, reason: "WebGPU 适配器不可用（可能是软件渲染或显卡被禁用）" };
    return { available: true, reason: "" };
  } catch (error) {
    return { available: false, reason: `WebGPU 适配器检测失败：${error.message}` };
  }
}

function progressHandler(requestId, backend) {
  return (event) => {
    if (!event || event.status === "ready") return;
    if (event.status === "progress" && event.total) {
      post({
        type: "model-progress",
        requestId,
        backend,
        file: event.file,
        loaded: event.loaded,
        total: event.total,
        progress: Math.round((event.loaded / event.total) * 100),
      });
    } else if (event.status === "initiate" || event.status === "download") {
      post({ type: "model-progress", requestId, backend, file: event.file, loaded: 0, total: 0, progress: 0 });
    }
  };
}

async function createPipeline(backend, requestId) {
  const isWebGPU = backend === "webgpu";
  const dtype = isWebGPU ? "fp16" : "q8";
  post({ type: "backend-attempt", requestId, backend, dtype });
  const startedAt = performance.now();
  const instance = await pipeline("feature-extraction", MODEL_ID, {
    device: backend,
    dtype,
    pooling: "cls",
    normalize: true,
    progress_callback: progressHandler(requestId, backend),
  });
  return { instance, dtype, loadMs: performance.now() - startedAt };
}

async function init(requestId, requestedBackend = "auto") {
  if (extractor && (requestedBackend === "auto" || requestedBackend === activeBackend)) {
    post({
      type: "init-result",
      requestId,
      backend: activeBackend,
      dtype: activeDtype,
      loadMs,
      cached: true,
    });
    return;
  }

  if (extractor?.dispose) {
    try {
      await extractor.dispose();
    } catch {
      // Ignore disposal errors; a fresh pipeline can still be created.
    }
    extractor = null;
  }

  const candidates = [];
  let webgpuReason = "";
  if (requestedBackend === "auto" || requestedBackend === "webgpu") {
    const detected = await detectWebGPU();
    if (detected.available) candidates.push("webgpu");
    else webgpuReason = detected.reason;
  }
  if (requestedBackend === "auto" || requestedBackend === "wasm") candidates.push("wasm");
  if (candidates.length === 0) candidates.push("wasm");

  const failures = [];
  for (const backend of candidates) {
    try {
      const created = await createPipeline(backend, requestId);
      extractor = created.instance;
      activeBackend = backend;
      activeDtype = created.dtype;
      loadMs = created.loadMs;
      post({
        type: "init-result",
        requestId,
        backend,
        dtype: activeDtype,
        loadMs,
        cached: false,
        webgpuReason: backend === "wasm" ? webgpuReason || failures[0]?.message || "" : "",
        failures,
      });
      return;
    } catch (error) {
      failures.push({ backend, message: error.stack || error.message || String(error) });
      post({ type: "backend-failed", requestId, backend, message: error.stack || error.message || String(error) });
    }
  }

  post({
    type: "init-error",
    requestId,
    message: `模型初始化失败：${failures.map((item) => `${item.backend}: ${item.message}`).join(" | ")}`,
    failures,
    webgpuReason,
  });
}

async function embed(requestId, texts, batchSize = 8) {
  if (!extractor) {
    post({ type: "embed-error", requestId, message: "模型尚未初始化" });
    return;
  }
  const input = Array.isArray(texts) ? texts : [texts];
  const size = Math.max(1, Math.min(32, Number(batchSize) || 8));
  const startedAt = performance.now();
  const vectors = [];
  const batchMs = [];

  for (let offset = 0; offset < input.length; offset += size) {
    const batch = input.slice(offset, offset + size);
    const t0 = performance.now();
    const output = await extractor(batch, { pooling: "cls", normalize: true });
    const dims = output.dims;
    const data = output.data;
    const dimension = dims[dims.length - 1];
    if (dimension !== MODEL_DIM) {
      post({ type: "embed-error", requestId, message: `模型输出维度 ${dimension} 与预期 ${MODEL_DIM} 不一致` });
      return;
    }
    for (let index = 0; index < batch.length; index += 1) {
      const vector = new Float32Array(dimension);
      vector.set(data.subarray(index * dimension, (index + 1) * dimension));
      vectors.push(vector);
    }
    const elapsed = performance.now() - t0;
    batchMs.push(Number(elapsed.toFixed(2)));
    post({
      type: "embed-progress",
      requestId,
      done: Math.min(input.length, offset + batch.length),
      total: input.length,
      batchMs: Number(elapsed.toFixed(2)),
      elapsedMs: Number((performance.now() - startedAt).toFixed(2)),
    });
  }

  post(
    {
      type: "embed-result",
      requestId,
      embeddings: vectors,
      elapsedMs: Number((performance.now() - startedAt).toFixed(2)),
      batchMs,
      backend: activeBackend,
      dtype: activeDtype,
    },
    vectors.map((vector) => vector.buffer),
  );
}

self.addEventListener("message", (event) => {
  const data = event.data || {};
  if (data.type === "init") {
    init(data.requestId, data.backend || "auto").catch((error) => {
      post({ type: "init-error", requestId: data.requestId, message: error.message || String(error) });
    });
  } else if (data.type === "embed") {
    embed(data.requestId, data.texts, data.batchSize).catch((error) => {
      post({ type: "embed-error", requestId: data.requestId, message: error.message || String(error) });
    });
  }
});

post({ type: "worker-ready" });
