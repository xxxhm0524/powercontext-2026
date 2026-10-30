#!/usr/bin/env node
/**
 * Download the ONNX model variants used by the app.
 *
 * The default mirror works in mainland China; set HF_MIRROR=https://huggingface.co
 * if you have direct Hugging Face access. Files are written to models/<MODEL_ID>/.
 */
import fs from "node:fs/promises";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const MODEL_ID = process.env.MODEL_ID || "bge-small-zh-v1.5";
const REPO = process.env.MODEL_REPO || "Xenova/bge-small-zh-v1.5";
const MIRROR = (process.env.HF_MIRROR || "https://hf-mirror.com").replace(/\/$/, "");
// hf-mirror caches the main branch. The exact upstream commit is recorded in the
// manifest and in server/config.mjs for provenance; the downloaded files are
// additionally pinned by SHA-256 in model-manifest.json.
const REVISION = process.env.MODEL_REVISION || "main";
const UPSTREAM_REVISION = "75c43b069aac4d136ba6bc1122f995fedcfd2781";
const TARGET_DIR = path.join(ROOT, "models", MODEL_ID);
const TARGET_ONNX = path.join(TARGET_DIR, "onnx");

const BASE_FILES = [
  "config.json",
  "tokenizer.json",
  "tokenizer_config.json",
  "special_tokens_map.json",
  "vocab.txt",
];
const ONNX_FILES = [
  { name: "onnx/model.onnx", label: "FP32 baseline", required: true },
  { name: "onnx/model_fp16.onnx", label: "FP16", required: true },
  { name: "onnx/model_quantized.onnx", label: "INT8 dynamic", required: true },
];

function human(bytes) {
  if (!bytes) return "0 B";
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

async function headSize(url) {
  try {
    const response = await fetch(url, { method: "HEAD", redirect: "follow" });
    if (!response.ok) return null;
    const value = response.headers.get("content-length");
    return value ? Number(value) : null;
  } catch {
    return null;
  }
}

async function download(relative, label, required) {
  const destination = path.join(TARGET_DIR, relative);
  await fs.mkdir(path.dirname(destination), { recursive: true });
  try {
    const stat = await fs.stat(destination);
    if (stat.size > 0) {
      console.log(`[model] ${label.padEnd(14)} ${relative.padEnd(30)} exists ${human(stat.size)}`);
      return stat.size;
    }
  } catch {
    // missing, download below
  }

  const encodedPath = relative.split("/").map(encodeURIComponent).join("/");
  const url = `${MIRROR}/${REPO}/resolve/${REVISION}/${encodedPath}`;
  const expected = await headSize(url);
  console.log(`[model] ${label.padEnd(14)} ${relative.padEnd(30)} downloading ${expected ? human(expected) : ""}`);
  const response = await fetch(url, { redirect: "follow" });
  if (!response.ok) {
    if (!required) {
      console.warn(`[model] skip ${relative}: HTTP ${response.status}`);
      return 0;
    }
    throw new Error(`下载失败 ${url}: HTTP ${response.status} ${response.statusText}`);
  }

  const total = Number(response.headers.get("content-length") || 0);
  const chunks = [];
  let received = 0;
  let lastReport = 0;
  for await (const chunk of response.body) {
    chunks.push(Buffer.from(chunk));
    received += chunk.length;
    if (total && Date.now() - lastReport > 1000) {
      lastReport = Date.now();
      const percent = ((received / total) * 100).toFixed(0);
      console.log(`         ${relative} ${percent}% (${human(received)} / ${human(total)})`);
    }
  }
  const buffer = Buffer.concat(chunks);
  await fs.writeFile(destination, buffer);
  console.log(`[model] ${label.padEnd(14)} ${relative.padEnd(30)} done ${human(buffer.length)}`);
  return buffer.length;
}

async function sha256(file) {
  const hash = crypto.createHash("sha256");
  hash.update(await fs.readFile(file));
  return hash.digest("hex");
}

async function main() {
  console.log(`[model] repo=${REPO} revision=${REVISION}`);
  console.log(`[model] mirror=${MIRROR}`);
  for (const file of BASE_FILES) await download(file, "tokenizer", true);
  const sizes = {};
  for (const file of ONNX_FILES) {
    sizes[file.name] = await download(file.name, file.label, file.required);
  }

  const manifest = {
    modelId: MODEL_ID,
    repo: REPO,
    revision: REVISION,
    upstreamRevision: UPSTREAM_REVISION,
    mirror: MIRROR,
    generatedAt: new Date().toISOString(),
    files: {},
  };
  const allFiles = [...BASE_FILES, ...ONNX_FILES.map((item) => item.name)];
  for (const relative of allFiles) {
    const full = path.join(TARGET_DIR, relative);
    const stat = await fs.stat(full);
    manifest.files[relative] = { bytes: stat.size, sha256: await sha256(full) };
  }
  await fs.writeFile(path.join(TARGET_DIR, "model-manifest.json"), `${JSON.stringify(manifest, null, 2)}\n`);

  const fp32 = sizes["onnx/model.onnx"];
  const fp16 = sizes["onnx/model_fp16.onnx"];
  const int8 = sizes["onnx/model_quantized.onnx"];
  console.log("");
  console.log(`[model] FP32 ${human(fp32)} | FP16 ${human(fp16)} (${(fp32 / fp16).toFixed(2)}x) | INT8 ${human(int8)} (${(fp32 / int8).toFixed(2)}x)`);
  console.log(`[model] manifest -> ${path.join(TARGET_DIR, "model-manifest.json")}`);
}

main().catch((error) => {
  console.error(`[model] ${error.message}`);
  process.exit(1);
});
