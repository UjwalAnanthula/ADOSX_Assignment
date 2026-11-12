import { useCallback, useEffect, useRef, useState } from "react";
import { fetchDiscrepancies, fetchOrgs, fetchSummary } from "./api.js";
import { displayB, displayDifference, displayValue, nextOrdering } from "./format.js";
import Icon from "./Icon.jsx";
import { SUMMARY_CARDS, reasonMeta } from "./reasons.js";

const SORTS = [
  { value: "", label: "Record id" },
  { value: "-a_value", label: "System A value, high to low" },
  { value: "a_value", label: "System A value, low to high" },
  { value: "-b_value", label: "System B value, high to low" },
  { value: "b_value", label: "System B value, low to high" },
];

const dateFmt = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

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

function ValueCell({ cell, diff = false }) {
  let cls = { number: "num", none: "num muted", blank: "num bad", invalid: "num bad" }[cell.kind];
  if (diff && cell.sign) cls += " diff-nonzero";
  if (diff && cell.sign === 0) cls += " muted";
  return <td className={cls}>{cell.text}</td>;
}

function SortHeader({ field, label, ordering, onChange }) {
  const dir = ordering === field ? "ascending" : ordering === `-${field}` ? "descending" : "none";
  const icon = { ascending: "up", descending: "down", none: "sort" }[dir];
  return (
    <th aria-sort={dir} className="num">
      <button type="button" className={`sort ${dir !== "none" ? "is-active" : ""}`}
        onClick={() => onChange(nextOrdering(ordering, field))}>
        {label} <Icon name={icon} size={13} />
      </button>
    </th>
  );
}

function ReasonBadge({ code, label }) {
  const meta = reasonMeta(code);
  return <span className={`badge tone-${meta.tone}`} title={label}><span className="dot" />{meta.short}</span>;
}

function ImportStatus({ summary }) {
  if (!summary) return <span className="status-pill"><span className="status-dot idle" />Loading data…</span>;
  if (!summary.last_import) return <span className="status-pill"><span className="status-dot idle" />No import yet</span>;
  const when = new Date(summary.last_import);
  return (
    <span className="status-pill" title={`Last import: ${when.toISOString()}`}>
      <span className="status-dot ok" />Data imported · {dateFmt.format(when)}
    </span>
  );
}

function SkeletonRows() {
  return Array.from({ length: 5 }, (_, i) => (
    <tr key={i} className="skeleton" aria-hidden="true">
      {Array.from({ length: 8 }, (_, j) => <td key={j}><span className="bar" /></td>)}
    </tr>
  ));
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
  const countOf = (code) => summary?.reasons.find((r) => r.code === code)?.count ?? 0;
  const otherCount = total - SUMMARY_CARDS.reduce((n, c) => n + countOf(c.code), 0);
  const filtered = Boolean(reason || ordering);
  const resetFilters = () => { setReason(""); setOrdering(""); };

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark"><Icon name="swap" size={18} /></span>
          <div>
            <div className="brand-name">Reconciliation</div>
            <div className="brand-sub">Where System A and System B disagree</div>
          </div>
        </div>
        <div className="topbar-right">
          <ImportStatus summary={summary} />
          <label className="org-picker">
            <Icon name="building" />
            <span className="org-picker-label">Organisation</span>
            <select value={org} onChange={(e) => setOrg(e.target.value)} disabled={!orgs.length}>
              {orgs.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
          </label>
        </div>
      </header>

      <main className="page">
        <div className="page-head">
          <div>
            <h1>Disagreements {org && <span className="org-chip">{org}</span>}</h1>
            <p className="subtle">Only this organisation's records are shown. Values are compared exactly, to the cent.</p>
          </div>
          {summary && (
            <dl className="facts">
              <div><dt>System A records</dt><dd>{summary.import.system_a_rows}</dd></div>
              <div><dt>System B entries</dt><dd>{summary.import.system_b_rows}</dd></div>
              <div title="B rows whose reference or value was normalised or could not be parsed. Every row was kept.">
                <dt>Import notes</dt><dd>{summary.import.system_b_rows_with_issues}</dd>
              </div>
            </dl>
          )}
        </div>

        <section className="cards" aria-label="Summary">
          <button type="button" className={`card card-total ${!reason ? "is-active" : ""}`} aria-pressed={!reason}
            onClick={() => setReason("")} disabled={!summary}>
            <span className="card-title"><Icon name="layers" size={14} />Total disagreements</span>
            <span className="card-value">{summary ? total : "–"}</span>
            <span className="card-caption">{summary ? `incl. ${otherCount} other (date, voided, invalid value…)` : " "}</span>
          </button>
          {SUMMARY_CARDS.map((c) => {
            const n = countOf(c.code);
            const tone = reasonMeta(c.code).tone;
            return (
              <button key={c.code} type="button" className={`card ${reason === c.code ? "is-active" : ""}`}
                aria-pressed={reason === c.code} disabled={!summary || n === 0} onClick={() => setReason(c.code)}>
                <span className="card-title"><span className={`dot tone-${tone}`} />{c.title}</span>
                <span className="card-value">{summary ? n : "–"}</span>
                <span className="card-caption">{c.caption}</span>
              </button>
            );
          })}
        </section>

        <section className="panel">
          <div className="toolbar">
            <label className="field">
              <span className="field-label">Reason</span>
              <select value={reason} onChange={(e) => setReason(e.target.value)} disabled={!summary}>
                <option value="">All reasons ({total})</option>
                {reasons.map((r) => <option key={r.code} value={r.code}>{r.label} ({r.count})</option>)}
              </select>
            </label>
            <label className="field">
              <span className="field-label">Sort by</span>
              <select value={ordering} onChange={(e) => setOrdering(e.target.value)}>
                {SORTS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
              </select>
            </label>
            <button type="button" className="btn btn-ghost" onClick={resetFilters} disabled={!filtered}>
              <Icon name="x" size={14} />Reset filters
            </button>
            <span className="result-count" data-testid="status-line" aria-live="polite">
              {summary && status === "ready" ? <>Showing <strong>{rows.length}</strong> of {total}</> : null}
            </span>
          </div>

          {status === "error" && (
            <div className="alert" role="alert">
              <Icon name="alert" />
              <div><strong>Could not load data.</strong> <span className="alert-detail">{error}</span></div>
              <button type="button" className="btn" onClick={() => setReloadKey((k) => k + 1)}>
                <Icon name="retry" size={14} />Retry
              </button>
            </div>
          )}

          {status === "ready" && !orgs.length && (
            <div className="empty">
              <Icon name="database" size={28} />
              <p className="empty-title">No data imported</p>
              <p className="subtle">Run <code>python manage.py import_data</code>, then reload.</p>
            </div>
          )}
          {status === "ready" && orgs.length > 0 && rows.length === 0 && (
            <div className="empty">
              <Icon name="check" size={28} />
              <p className="empty-title">No disagreements for this selection</p>
              {filtered && <button type="button" className="btn" onClick={resetFilters}>Reset filters</button>}
            </div>
          )}

          {(status === "loading" || (status === "ready" && rows.length > 0)) && (
            <div className="table-wrap">
              <table aria-busy={status === "loading"}>
                <thead>
                  <tr>
                    <th>Record</th>
                    <th>Reason</th>
                    <SortHeader field="a_value" label="System A value" ordering={ordering} onChange={setOrdering} />
                    <SortHeader field="b_value" label="System B value" ordering={ordering} onChange={setOrdering} />
                    <th className="num">Difference (B − A)</th>
                    <th>Location</th>
                    <th>System B entries</th>
                    <th>Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {status === "loading" ? <SkeletonRows /> : rows.map((row) => (
                    <tr key={row.id}>
                      <td className="mono strong">{row.record_id || <span className="muted">(unreadable ref)</span>}</td>
                      <td><ReasonBadge code={row.reason} label={row.reason_label} /></td>
                      <ValueCell cell={displayValue(row.a_value)} />
                      <ValueCell cell={displayB(row)} />
                      <ValueCell cell={displayDifference(row)} diff />
                      <td className="mono">{row.location_id || "—"}</td>
                      <td>
                        {row.entry_ids.length
                          ? <span className="chips">{row.entry_ids.map((e) => <code key={e} className="chip">{e}</code>)}</span>
                          : <span className="muted">none</span>}
                      </td>
                      <td className="detail">{row.detail}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
