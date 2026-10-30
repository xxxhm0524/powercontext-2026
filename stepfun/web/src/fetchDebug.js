/**
 * Installed before Transformers.js is evaluated so every model/asset request is
 * visible in the UI's debug log. Also converts "SPA fallback returns index.html"
 * into an actionable error instead of an opaque JSON.parse failure.
 */
const nativeFetch = globalThis.fetch.bind(globalThis);

globalThis.fetch = async (input, init) => {
  const response = await nativeFetch(input, init);
  const contentType = response.headers.get("content-type") || "";
  try {
    self.postMessage({
      type: "fetch-debug",
      url: String(input),
      status: response.status,
      contentType,
      ok: response.ok,
    });
  } catch {
    // postMessage is unavailable during teardown; the fetch result is still returned.
  }
  if (contentType.includes("text/html") && !String(input).endsWith(".html")) {
    throw new Error(`模型资源请求返回 HTML：${String(input)} (HTTP ${response.status})`);
  }
  return response;
};
