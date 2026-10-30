import express from "express";
import fs from "node:fs";
import path from "node:path";
import { config, MODELS_DIR, WEB_DIST_DIR } from "./config.mjs";
import { KbService } from "./kb-service.mjs";
import { getModelInfo } from "./model-info.mjs";

const app = express();
const service = new KbService(config);

app.disable("x-powered-by");
if (process.env.DEBUG_MODELS === "1") {
  app.use((req, res, next) => {
    if (req.path.startsWith("/models")) console.log(`[models] ${req.method} ${req.originalUrl}`);
    next();
  });
}
app.use((req, res, next) => {
  res.setHeader("Cross-Origin-Opener-Policy", "same-origin");
  res.setHeader("Cross-Origin-Embedder-Policy", "require-corp");
  next();
});
app.use(express.json({ limit: "64mb" }));

const asyncRoute = (handler) => (req, res, next) => {
  Promise.resolve(handler(req, res, next)).catch(next);
};

app.get("/api/health", asyncRoute(async (req, res) => {
  let connected = false;
  let error = null;
  try {
    await service.connect();
    connected = true;
  } catch (err) {
    error = err.message;
  }
  res.json({
    ok: connected,
    seekdb: {
      mode: config.seekdb.mode,
      connected,
      host: config.seekdb.mode === "server" ? `${config.seekdb.host}:${config.seekdb.port}` : config.seekdb.path,
      database: config.seekdb.database,
      error,
    },
    model: await getModelInfo(),
    defaultKb: config.defaultKb,
    now: new Date().toISOString(),
  });
}));

app.get("/api/model-info", asyncRoute(async (req, res) => {
  res.json(await getModelInfo());
}));

app.get("/api/kbs", asyncRoute(async (req, res) => {
  await service.ensureDefaultKb();
  res.json({ kbs: await service.listKbs() });
}));

app.post("/api/kbs", asyncRoute(async (req, res) => {
  const name = String(req.body?.name || "").trim().toLowerCase();
  const normalized = name.startsWith("kb_") ? name : `kb_${name}`;
  res.status(201).json(await service.createKb(normalized));
}));

app.delete("/api/kbs/:name", asyncRoute(async (req, res) => {
  res.json(await service.deleteKb(req.params.name));
}));

app.post("/api/kbs/:name/reset", asyncRoute(async (req, res) => {
  res.json(await service.resetKb(req.params.name));
}));

app.get("/api/kbs/:name/stats", asyncRoute(async (req, res) => {
  res.json(await service.stats(req.params.name));
}));

app.get("/api/kbs/:name/documents", asyncRoute(async (req, res) => {
  res.json(await service.listDocuments(req.params.name, req.query.limit, req.query.offset));
}));

app.post("/api/kbs/:name/documents", asyncRoute(async (req, res) => {
  res.json(await service.addDocuments(req.params.name, req.body?.documents));
}));

app.post("/api/kbs/:name/refresh", asyncRoute(async (req, res) => {
  res.json(await service.refresh(req.params.name));
}));

app.post("/api/kbs/:name/search", asyncRoute(async (req, res) => {
  res.json(await service.search(req.params.name, {
    query: req.body?.query,
    embedding: req.body?.embedding,
    topK: req.body?.topK,
  }));
}));

app.use("/models", express.static(MODELS_DIR, {
  fallthrough: false,
  maxAge: "1d",
  setHeaders(res) {
    res.setHeader("Cache-Control", "public, max-age=86400, immutable");
  },
}));

if (fs.existsSync(WEB_DIST_DIR)) {
  app.use(express.static(WEB_DIST_DIR, { index: false, maxAge: "1h" }));
  app.get("*", (req, res, next) => {
    if (req.path.startsWith("/api/")) return next();
    res.sendFile(path.join(WEB_DIST_DIR, "index.html"));
  });
} else {
  app.get("/", (req, res) => {
    res.status(503).type("text/plain").send(
      "前端尚未构建。请先运行 `npm run build`，或使用 `npm run dev` 启动开发模式。",
    );
  });
}

app.use((err, req, res, next) => {
  const status = err.statusCode || (err.message?.includes("not found") ? 404 : 500);
  console.error(`[api] ${req.method} ${req.originalUrl}:`, err.message);
  if (res.headersSent) return next(err);
  res.status(status).json({ error: err.message || "Internal Server Error" });
});

const server = app.listen(config.port, async () => {
  console.log(`[stepfun] http://127.0.0.1:${config.port}`);
  console.log(`[stepfun] seekdb mode=${config.seekdb.mode} ` +
    (config.seekdb.mode === "server"
      ? `${config.seekdb.host}:${config.seekdb.port}/${config.seekdb.database}`
      : config.seekdb.path));
  try {
    await service.ensureDefaultKb();
    console.log(`[stepfun] default knowledge base ready: ${config.defaultKb}`);
  } catch (error) {
    console.error(`[stepfun] seekdb is not ready: ${error.message}`);
  }
});

async function shutdown(signal) {
  console.log(`\n[stepfun] ${signal}, closing...`);
  server.close();
  await service.close().catch(() => {});
  process.exit(0);
}
process.on("SIGINT", () => shutdown("SIGINT"));
process.on("SIGTERM", () => shutdown("SIGTERM"));
