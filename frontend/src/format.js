// How a value cell reads. Kept separate from React so it can be unit-tested.
// Returns { text, kind } where kind is "number" | "blank" | "invalid" | "none".

const fmt = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function displayValue(value) {
  if (value === null || value === undefined) return { text: "—", kind: "none" };
  const n = Number(value);
  return Number.isFinite(n) ? { text: fmt.format(n), kind: "number" } : { text: String(value), kind: "invalid" };
}

// System B cell: when B's value could not be parsed, show what B actually sent.
export function displayB(row) {
  if (row.b_value === null && row.reason === "UNPARSEABLE_VALUE") {
    const raw = row.b_raw_value ?? "";
    return raw.trim() === ""
      ? { text: "(blank in System B)", kind: "blank" }
      : { text: `not a number: "${raw}"`, kind: "invalid" };
  }
  return displayValue(row.b_value);
}
