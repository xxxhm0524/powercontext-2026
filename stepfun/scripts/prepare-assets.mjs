#!/usr/bin/env node
/** Copy ONNX Runtime Web WASM assets into the Vite public directory. */
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SOURCE_DIRS = [
  path.join(ROOT, "node_modules", "onnxruntime-web", "dist"),
  path.join(ROOT, "node_modules", "@huggingface", "transformers", "dist"),
];
const TARGET_DIR = path.join(ROOT, "web", "public", "ort");

async function main() {
  await fs.mkdir(TARGET_DIR, { recursive: true });
  let copied = 0;
  for (const source of SOURCE_DIRS) {
    let entries = [];
    try {
      entries = await fs.readdir(source);
    } catch {
      continue;
    }
    for (const entry of entries) {
      if (!/^ort-wasm.*\.(wasm|mjs)$/.test(entry)) continue;
      const destination = path.join(TARGET_DIR, entry);
      try {
        const [srcStat, dstStat] = await Promise.all([fs.stat(path.join(source, entry)), fs.stat(destination).catch(() => null)]);
        if (dstStat && dstStat.size === srcStat.size) continue;
        await fs.copyFile(path.join(source, entry), destination);
        copied += 1;
        console.log(`[assets] ${entry}`);
      } catch (error) {
        console.warn(`[assets] skip ${entry}: ${error.message}`);
      }
    }
  }
  console.log(`[assets] ${copied} file(s) prepared in web/public/ort`);
  if (copied === 0) {
    const existing = await fs.readdir(TARGET_DIR).catch(() => []);
    if (existing.length === 0) console.warn("[assets] warning: no ONNX Runtime Web assets found; run npm install first");
  }
}

main().catch((error) => {
  console.error(`[assets] ${error.message}`);
  process.exit(1);
});
