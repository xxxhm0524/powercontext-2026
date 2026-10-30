import "dotenv/config";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
export const ROOT_DIR = path.resolve(here, "..");
export const WEB_DIST_DIR = path.join(ROOT_DIR, "web", "dist");
export const MODELS_DIR = path.join(ROOT_DIR, "models");
export const DATA_DIR = path.join(ROOT_DIR, "data");

const mode = (process.env.SEEKDB_MODE || (process.env.SEEKDB_HOST ? "server" : "embedded")).toLowerCase();

export const config = {
  port: Number(process.env.PORT || 5178),
  seekdb: {
    mode,
    host: process.env.SEEKDB_HOST || "127.0.0.1",
    port: Number(process.env.SEEKDB_PORT || 2881),
    user: process.env.SEEKDB_USER || "root",
    password: process.env.SEEKDB_PASSWORD || "",
    database: process.env.SEEKDB_DATABASE || "test",
    tenant: process.env.SEEKDB_TENANT || "",
    path: process.env.SEEKDB_PATH || path.join(DATA_DIR, "seekdb"),
  },
  model: {
    id: process.env.MODEL_ID || "bge-small-zh-v1.5",
    dimension: Number(process.env.MODEL_DIM || 512),
    repo: "Xenova/bge-small-zh-v1.5",
    revision: "75c43b069aac4d136ba6bc1122f995fedcfd2781",
    license: "MIT",
    upstream: "BAAI/bge-small-zh-v1.5",
  },
  defaultKb: "kb_stepfun_demo",
};
