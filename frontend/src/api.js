// Every tenant-data request carries the org header; the backend enforces the boundary.
async function request(path, org) {
  const res = await fetch(path, { headers: org ? { "X-Org-Id": org } : {} });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${body}`);
  }
  return res.json();
}

export const fetchOrgs = () => request("/api/orgs/");
export const fetchSummary = (org) => request("/api/summary/", org);
export function fetchDiscrepancies(org, { reason, ordering }) {
  const q = new URLSearchParams();
  if (reason) q.set("reason", reason);
  if (ordering) q.set("ordering", ordering);
  const qs = q.toString();
  return request(`/api/discrepancies/${qs ? `?${qs}` : ""}`, org);
}
