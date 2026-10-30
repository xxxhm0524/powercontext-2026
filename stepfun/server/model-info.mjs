import fs from "node:fs/promises";
import path from "node:path";
import { MODELS_DIR, config } from "./config.mjs";

const FILE_SPECS = {
  fp32: "onnx/model.onnx",
  fp16: "onnx/model_fp16.onnx",
  int8: "onnx/model_quantized.onnx",
};

let cached = null;

async function sizeOf(file) {
  try {
    const stat = await fs.stat(file);
    return stat.size;
  } catch {
    return null;
  }
}

export async function getModelInfo() {
  if (cached) return cached;
  const modelDir = path.join(MODELS_DIR, config.model.id);
  const files = {};
  for (const [precision, relative] of Object.entries(FILE_SPECS)) {
    const bytes = await sizeOf(path.join(modelDir, relative));
    files[precision] = {
      path: `${config.model.id}/${relative}`,
      bytes,
      mib: bytes ? Number((bytes / 1024 / 1024).toFixed(2)) : null,
      available: bytes !== null,
    };
  }
  const base = files.fp32.bytes;
  cached = {
    ...config.model,
    files,
    compression: {
      fp16: base && files.fp16.bytes ? Number((base / files.fp16.bytes).toFixed(2)) : null,
      int8: base && files.int8.bytes ? Number((base / files.int8.bytes).toFixed(2)) : null,
    },
    ready: files.int8.available && files.fp16.available,
  };
  return cached;
}

export function resetModelInfoCache() {
  cached = null;
}
