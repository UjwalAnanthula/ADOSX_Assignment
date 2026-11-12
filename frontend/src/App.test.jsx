// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App.jsx";

const ROWS = {
  "ORG-A": [
    { id: 1, reason: "VALUE_MISMATCH", reason_label: "Systems report different values", record_id: "REC-1027",
      entry_ids: ["ENT/1"], location_id: "LOC-102", a_value: "79259.03", b_value: "61921.12", b_raw_value: "61921.12", detail: "" },
    { id: 2, reason: "MISSING_IN_B", reason_label: "Record has no entry in System B", record_id: "REC-1015",
      entry_ids: [], location_id: "LOC-103", a_value: "41095.33", b_value: null, b_raw_value: "", detail: "" },
  ],
  "ORG-B": [
    { id: 3, reason: "UNPARSEABLE_VALUE", reason_label: "Value missing or not a number", record_id: "REC-1050",
      entry_ids: ["ENT/2"], location_id: "LOC-202", a_value: "160405.85", b_value: null, b_raw_value: "", detail: "" },
    // Same reason as an ORG-A row, so the org-switch test proves the filter is reset on purpose,
    // not merely dropped because the new org lacks that reason.
    { id: 4, reason: "MISSING_IN_B", reason_label: "Record has no entry in System B", record_id: "REC-1061",
      entry_ids: [], location_id: "LOC-202", a_value: "87615.49", b_value: null, b_raw_value: "", detail: "" },
  ],
};

function summaryFor(org) {
  const counts = {};
  ROWS[org].forEach((r) => { counts[r.reason] = (counts[r.reason] || 0) + 1; });
  return {
    org,
    reasons: Object.entries(counts).map(([code, count]) => ({ code, label: code, count })),
    import: { system_a_rows: 1, system_b_rows: 1, system_b_rows_with_issues: 0 },
  };
}

const ok = (body) => ({ ok: true, status: 200, statusText: "OK", json: async () => body, text: async () => "" });
const fail = () => ({ ok: false, status: 500, statusText: "Server Error", json: async () => ({}), text: async () => "boom" });

let calls;
let failNextDiscrepancies;

beforeEach(() => {
  calls = [];
  failNextDiscrepancies = false;
  window.history.replaceState(null, "", "/");
  globalThis.fetch = vi.fn(async (url, opts = {}) => {
    const org = opts.headers?.["X-Org-Id"];
    const u = new URL(url, "http://localhost");
    calls.push({ path: u.pathname, org, params: Object.fromEntries(u.searchParams) });
    if (u.pathname === "/api/orgs/") return ok(Object.keys(ROWS));
    if (!org) return { ...fail(), status: 400 };
    if (u.pathname === "/api/summary/") return ok(summaryFor(org));
    if (failNextDiscrepancies) { failNextDiscrepancies = false; return fail(); }
    const reason = u.searchParams.get("reason");
    return ok(ROWS[org].filter((r) => !reason || r.reason === reason));
  });
});

afterEach(cleanup);

const tableRows = () => screen.getAllByRole("row").slice(1); // drop header row

describe("App", () => {
  it("shows the first org's disagreements and scopes every tenant request with X-Org-Id", async () => {
    render(<App />);
    expect(await screen.findByText("REC-1027")).toBeTruthy();
    expect(tableRows()).toHaveLength(2);
    const tenantCalls = calls.filter((c) => c.path !== "/api/orgs/");
    expect(tenantCalls.length).toBeGreaterThan(0);
    expect(tenantCalls.every((c) => c.org === "ORG-A")).toBe(true);
  });

  it("switching org shows only that org's rows and clears the reason filter", async () => {
    render(<App />);
    await screen.findByText("REC-1027");
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "MISSING_IN_B" } });
    await waitFor(() => expect(tableRows()).toHaveLength(1));

    fireEvent.change(screen.getByLabelText("Organisation"), { target: { value: "ORG-B" } });
    expect(await screen.findByText("REC-1050")).toBeTruthy(); // not MISSING_IN_B: only visible if the filter was cleared
    expect(screen.getByText("REC-1061")).toBeTruthy();
    expect(screen.queryByText("REC-1027")).toBeNull();
    expect(screen.getByLabelText("Reason").value).toBe("");
    const last = calls.filter((c) => c.path === "/api/discrepancies/").at(-1);
    expect(last).toEqual({ path: "/api/discrepancies/", org: "ORG-B", params: {} });
  });

  it("shows a blank System B value as blank, not as 0, and no difference", async () => {
    window.history.replaceState(null, "", "/?org=ORG-B");
    render(<App />);
    const row = (await screen.findByText("REC-1050")).closest("tr");
    expect(within(row).getByText("(blank in System B)")).toBeTruthy();
    expect(within(row).getAllByText("—").length).toBeGreaterThan(0);
  });

  it("clicking the System B value header sorts high-to-low, then low-to-high", async () => {
    render(<App />);
    await screen.findByText("REC-1027");
    fireEvent.click(screen.getByRole("button", { name: /System B value/ }));
    await waitFor(() => expect(calls.at(-1).params.ordering).toBe("-b_value"));
    await screen.findByText("REC-1027");
    fireEvent.click(screen.getByRole("button", { name: /System B value/ }));
    await waitFor(() => expect(calls.at(-1).params.ordering).toBe("b_value"));
    expect(screen.getByLabelText("Sort by").value).toBe("b_value");
  });

  it("shows an error with a working Retry", async () => {
    failNextDiscrepancies = true;
    render(<App />);
    expect((await screen.findByRole("alert")).textContent).toMatch(/Could not load data/);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("REC-1027")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("drops an unknown reason from the URL instead of sending it to the API", async () => {
    window.history.replaceState(null, "", "/?org=ORG-A&reason=NOT_A_REASON");
    render(<App />);
    await screen.findByText("REC-1027");
    expect(calls.some((c) => c.params.reason === "NOT_A_REASON")).toBe(false);
    expect(window.location.search).toBe("?org=ORG-A");
  });
});
