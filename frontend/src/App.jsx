import { useEffect, useState } from "react";
import { fetchDiscrepancies, fetchOrgs, fetchSummary } from "./api.js";
import { displayB, displayValue } from "./format.js";

const SORTS = [
  { value: "", label: "Record id" },
  { value: "-a_value", label: "System A value, high to low" },
  { value: "a_value", label: "System A value, low to high" },
  { value: "-b_value", label: "System B value, high to low" },
  { value: "b_value", label: "System B value, low to high" },
];

function ValueCell({ cell }) {
  const cls = cell.kind === "number" ? "num" : cell.kind === "none" ? "num muted" : "num bad";
  return <td className={cls}>{cell.text}</td>;
}

export default function App() {
  const [orgs, setOrgs] = useState([]);
  const [org, setOrg] = useState("");
  const [summary, setSummary] = useState(null);
  const [reason, setReason] = useState("");
  const [ordering, setOrdering] = useState("");
  const [rows, setRows] = useState([]);
  const [status, setStatus] = useState("loading"); // loading | ready | error
  const [error, setError] = useState("");

  useEffect(() => {
    fetchOrgs()
      .then((list) => {
        setOrgs(list);
        setOrg(list[0] || "");
        if (!list.length) setStatus("ready");
      })
      .catch((e) => { setError(e.message); setStatus("error"); });
  }, []);

  // Switching tenant resets the reason filter: reasons/counts are per tenant.
  useEffect(() => {
    if (!org) return;
    setReason("");
    setSummary(null);
    fetchSummary(org).then(setSummary).catch((e) => { setError(e.message); setStatus("error"); });
  }, [org]);

  useEffect(() => {
    if (!org) return;
    let cancelled = false;
    setStatus("loading");
    fetchDiscrepancies(org, { reason, ordering })
      .then((data) => { if (!cancelled) { setRows(data); setStatus("ready"); } })
      .catch((e) => { if (!cancelled) { setError(e.message); setStatus("error"); } });
    return () => { cancelled = true; };
  }, [org, reason, ordering]);

  const reasons = summary ? summary.reasons.filter((r) => r.count > 0) : [];
  const total = reasons.reduce((n, r) => n + r.count, 0);

  return (
    <main>
      <h1>System A vs System B: disagreements</h1>

      <div className="controls">
        <label>
          Organisation
          <select value={org} onChange={(e) => setOrg(e.target.value)} disabled={!orgs.length}>
            {orgs.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        </label>
        <label>
          Reason
          <select value={reason} onChange={(e) => setReason(e.target.value)}>
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
        <p className="meta">
          {org}: {summary.import.system_a_rows} System A rows, {summary.import.system_b_rows} System B rows
          ({summary.import.system_b_rows_with_issues} with import notes).
        </p>
      )}

      {status === "error" && <p className="error" role="alert">Could not load data. {error}</p>}
      {status === "loading" && <p className="meta">Loading…</p>}
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
                <th>System A value</th>
                <th>System B value</th>
                <th>Location</th>
                <th>System B entries</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>{row.record_id || <span className="muted">(unreadable ref)</span>}</td>
                  <td>{row.reason_label}</td>
                  <ValueCell cell={displayValue(row.a_value)} />
                  <ValueCell cell={displayB(row)} />
                  <td>{row.location_id || "—"}</td>
                  <td>{row.entry_ids.length ? row.entry_ids.join(", ") : <span className="muted">none</span>}</td>
                  <td>{row.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
