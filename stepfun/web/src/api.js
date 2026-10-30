async function request(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || `HTTP ${response.status}`);
  }
  return payload;
}

export const api = {
  health: () => request("/api/health"),
  modelInfo: () => request("/api/model-info"),
  listKbs: () => request("/api/kbs"),
  createKb: (name) => request("/api/kbs", { method: "POST", body: JSON.stringify({ name }) }),
  deleteKb: (name) => request(`/api/kbs/${encodeURIComponent(name)}`, { method: "DELETE" }),
  resetKb: (name) => request(`/api/kbs/${encodeURIComponent(name)}/reset`, { method: "POST" }),
  stats: (name) => request(`/api/kbs/${encodeURIComponent(name)}/stats`),
  documents: (name) => request(`/api/kbs/${encodeURIComponent(name)}/documents?limit=300`),
  addDocuments: (name, documents) =>
    request(`/api/kbs/${encodeURIComponent(name)}/documents`, {
      method: "POST",
      body: JSON.stringify({ documents }),
    }),
  search: (name, payload) =>
    request(`/api/kbs/${encodeURIComponent(name)}/search`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  refresh: (name) => request(`/api/kbs/${encodeURIComponent(name)}/refresh`, { method: "POST" }),
};
