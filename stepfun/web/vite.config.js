import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");

export default defineConfig({
  root: here,
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.join(here, "src"),
    },
  },
  server: {
    port: 5179,
    proxy: {
      "/api": "http://127.0.0.1:5178",
      "/models": "http://127.0.0.1:5178",
    },
  },
  build: {
    outDir: path.join(here, "dist"),
    emptyOutDir: true,
    sourcemap: false,
    target: "es2022",
  },
  optimizeDeps: {
    exclude: ["@huggingface/transformers"],
  },
});
