// How value cells read. Kept separate from React so it can be unit-tested.
// Each helper returns { text, kind } where kind is "number" | "blank" | "invalid" | "none".

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

// B − A, computed in integer cents so 0.1 + 0.2 style float noise never shows up.
export function displayDifference(row) {
  const a = Number(row.a_value);
  const b = Number(row.b_value);
  if (row.a_value == null || row.b_value == null || !Number.isFinite(a) || !Number.isFinite(b)) {
    return { text: "—", kind: "none" };
  }
  const cents = Math.round(b * 100) - Math.round(a * 100);
  if (cents === 0) return { text: "0.00", kind: "number" };
  return { text: `${cents > 0 ? "+" : "−"}${fmt.format(Math.abs(cents) / 100)}`, kind: "number" };
}

// Header click cycles: not sorted -> high to low -> low to high -> not sorted.
export function nextOrdering(current, field) {
  if (current === `-${field}`) return field;
  if (current === field) return "";
  return `-${field}`;
}
