// The browser never names the tenant on a data request. It asks the server for a
// tenant context (demo stand-in for login) and then sends only the server-signed
// token; the backend decides the tenant from that token alone (backend/recon/tenancy.py).
async function request(path, { token, method = "GET", body } = {}) {
  const headers = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body) headers["Content-Type"] = "application/json";
  const res = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  return res.json();
}

export const fetchOrgs = () => request("/api/orgs/");
// Demo only: switching tenant is an explicit server action that returns { org, token }.
export const createTenantContext = (org) => request("/api/tenant-context/", { method: "POST", body: { org } });
export const fetchSummary = (token) => request("/api/summary/", { token });
export function fetchDiscrepancies(token, { reason, ordering }) {
  const q = new URLSearchParams();
  if (reason) q.set("reason", reason);
  if (ordering) q.set("ordering", ordering);
  const qs = q.toString();
  return request(`/api/discrepancies/${qs ? `?${qs}` : ""}`, { token });
}
