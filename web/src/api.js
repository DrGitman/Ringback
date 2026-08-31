// The only place in the frontend that knows the backend's URL. Every other
// component calls listCases()/createCase() and knows nothing about where
// the API actually lives - same boundary app/calle_client.py draws around
// CALL-E on the backend.
//
// VITE_API_URL is baked in at build time (Vite inlines import.meta.env.*
// during the build, not read at runtime) - changing it after a Netlify
// deploy requires a rebuild, not just an env var change. Left unset, it
// defaults to "" (relative paths), which is what local dev wants: Vite's
// dev server proxies /api to localhost:8000 (see vite.config.js), so
// nothing needs configuring to run this locally.
const API_BASE = import.meta.env.VITE_API_URL || "";

async function request(path, options) {
  const res = await fetch(`${API_BASE}${path}`, options);
  return res;
}

export async function listCases(tenantId = "nust") {
  const res = await request(`/api/cases?tenant_id=${encodeURIComponent(tenantId)}`);
  if (!res.ok) throw new Error("Could not load cases.");
  return res.json();
}

export async function getCase(caseId) {
  const res = await request(`/api/cases/${caseId}`);
  if (!res.ok) throw new Error("Case not found.");
  return res.json();
}

export async function createCase(payload) {
  return request("/api/cases", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function listCountries() {
  const res = await request("/api/countries");
  if (!res.ok) throw new Error("Could not load country list.");
  return res.json();
}

export async function listOffices(tenantId = "nust") {
  const res = await request(`/api/tenants/${encodeURIComponent(tenantId)}/offices`);
  if (!res.ok) throw new Error("Could not load office list.");
  return res.json();
}

export async function routeCase(caseId, officeKey, reason) {
  const res = await request(`/api/cases/${caseId}/route`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ office_key: officeKey, reason }),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail || "Could not route this case.");
  return res.json();
}

export async function markCaseHandled(caseId, note) {
  const res = await request(`/api/cases/${caseId}/mark-handled`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ note }),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail || "Could not mark this case handled.");
  return res.json();
}
