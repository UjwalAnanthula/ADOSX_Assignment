import { useCallback, useEffect, useRef, useState } from "react";
import { fetchDiscrepancies, fetchOrgs, fetchSummary } from "./api.js";
import { displayB, displayDifference, displayValue, nextOrdering } from "./format.js";

const SORTS = [
  { value: "", label: "Record id" },
  { value: "-a_value", label: "System A value, high to low" },
  { value: "a_value", label: "System A value, low to high" },
  { value: "-b_value", label: "System B value, high to low" },
  { value: "b_value", label: "System B value, low to high" },
];

// org / reason / ordering live in the URL so a reload or a shared link keeps the view.
function readUrlState() {
  const q = new URLSearchParams(window.location.search);
  return { org: q.get("org") || "", reason: q.get("reason") || "", ordering: q.get("ordering") || "" };
}

function writeUrlState({ org, reason, ordering }) {
  const q = new URLSearchParams();
  if (org) q.set("org", org);
  if (reason) q.set("reason", reason);
  if (ordering) q.set("ordering", ordering);
  const qs = q.toString();
  window.history.replaceState(null, "", `${window.location.pathname}${qs ? `?${qs}` : ""}`);
}

function ValueCell({ cell }) {
  const cls = { number: "num", none: "num muted", blank: "num bad", invalid: "num bad" }[cell.kind];
  return <td className={cls}>{cell.text}</td>;
}

function SortHeader({ field, label, ordering, onChange }) {
  const dir = ordering === field ? "ascending" : ordering === `-${field}` ? "descending" : "none";
  const arrow = { ascending: "▲", descending: "▼", none: "↕" }[dir];
  return (
    <th aria-sort={dir} className="num">
      <button type="button" className="sort" onClick={() => onChange(nextOrdering(ordering, field))}>
        {label} <span aria-hidden="true">{arrow}</span>
      </button>
    </th>
  );
}

export default function App() {
  const initial = useRef(readUrlState()).current;
  const [orgs, setOrgs] = useState([]);
  const [org, setOrg] = useState("");
  const [summary, setSummary] = useState(null);
  const [reason, setReason] = useState(initial.reason);
  const [ordering, setOrdering] = useState(SORTS.some((s) => s.value === initial.ordering) ? initial.ordering : "");
  const [rows, setRows] = useState([]);
  const [status, setStatus] = useState("loading"); // loading | ready | error
  const [error, setError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const previousOrg = useRef("");

  const fail = useCallback((e) => { setError(e.message); setStatus("error"); }, []);

  useEffect(() => {
    setStatus("loading");
    fetchOrgs()
      .then((list) => {
        setOrgs(list);
        // Keep the current tenant across a retry; otherwise prefer the URL's, then the first.
        setOrg((prev) => (list.includes(prev) ? prev : list.includes(initial.org) ? initial.org : list[0] || ""));
        if (!list.length) setStatus("ready");
      })
      .catch(fail);
  }, [initial.org, fail, reloadKey]);

  // Reasons and counts are per tenant, so a tenant switch clears the reason filter
  // (but not on first load, where the reason may come from the URL).
  useEffect(() => {
    if (!org) return;
    if (previousOrg.current && previousOrg.current !== org) setReason("");
    previousOrg.current = org;
    setSummary(null);
    setStatus("loading");
    fetchSummary(org).then(setSummary).catch(fail);
  }, [org, fail, reloadKey]);

  // Waits for this tenant's summary so a stale/unknown reason (e.g. from an old link)
  // is dropped before it reaches the API. A Retry refetches the summary, which re-runs this.
  useEffect(() => {
    if (!org || !summary || summary.org !== org) return;
    if (reason && !summary.reasons.some((r) => r.code === reason && r.count > 0)) {
      setReason("");
      return;
    }
    writeUrlState({ org, reason, ordering });
    let cancelled = false;
    setStatus("loading");
    fetchDiscrepancies(org, { reason, ordering })
      .then((data) => { if (!cancelled) { setRows(data); setStatus("ready"); } })
      .catch((e) => { if (!cancelled) fail(e); });
    return () => { cancelled = true; };
  }, [org, summary, reason, ordering, fail]);

  const reasons = summary ? summary.reasons.filter((r) => r.count > 0) : [];
  const total = reasons.reduce((n, r) => n + r.count, 0);

  return (
    <main>
      <header>
        <h1>System A vs System B: disagreements</h1>
        <p className="meta">Records where the two systems disagree. You only see your organisation's rows.</p>
      </header>

      <div className="controls">
        <label>
          Organisation
          <select value={org} onChange={(e) => setOrg(e.target.value)} disabled={!orgs.length}>
            {orgs.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        </label>
        <label>
          Reason
          <select value={reason} onChange={(e) => setReason(e.target.value)} disabled={!summary}>
            <option value="">All reasons ({total})</option>
            {reasons.map((r) => <option key={r.code} value={r.code}>{r.label} ({r.count})</option>)}
          </select>
        </label>
        <label>
          Sort by
          <select value={ordering} onChange={(e) => setOrdering(e.target.value)}>
            {SORTS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </select>
        </label>
      </div>

      {summary && (
        <p className="meta" data-testid="status-line">
          Showing {status === "ready" ? rows.length : "…"} of {total} disagreements for {org}
          {reason && <> · <button type="button" className="link" onClick={() => setReason("")}>Clear reason filter</button></>}
          <br />
          Imported: {summary.import.system_a_rows} System A rows, {summary.import.system_b_rows} System B rows
          ({summary.import.system_b_rows_with_issues} with import notes).
        </p>
      )}

      {status === "error" && (
        <div className="error" role="alert">
          <strong>Could not load data.</strong> {error}{" "}
          <button type="button" onClick={() => setReloadKey((k) => k + 1)}>Retry</button>
        </div>
      )}
      {status === "loading" && <p className="meta" role="status">Loading…</p>}
      {status === "ready" && !orgs.length && (
        <p className="meta">No organisations found. Run <code>python manage.py import_data</code> first.</p>
      )}
      {status === "ready" && orgs.length > 0 && rows.length === 0 && (
        <p className="meta">No disagreements for this selection.</p>
      )}

      {status === "ready" && rows.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Record</th>
                <th>Reason</th>
                <SortHeader field="a_value" label="System A value" ordering={ordering} onChange={setOrdering} />
                <SortHeader field="b_value" label="System B value" ordering={ordering} onChange={setOrdering} />
                <th className="num">B − A</th>
                <th>Location</th>
                <th>System B entries</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td className="id">{row.record_id || <span className="muted">(unreadable ref)</span>}</td>
                  <td><span className={`tag tag-${row.reason}`}>{row.reason_label}</span></td>
                  <ValueCell cell={displayValue(row.a_value)} />
                  <ValueCell cell={displayB(row)} />
                  <ValueCell cell={displayDifference(row)} />
                  <td className="id">{row.location_id || "—"}</td>
                  <td className="id">{row.entry_ids.length ? row.entry_ids.join(", ") : <span className="muted">none</span>}</td>
                  <td className="detail">{row.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
