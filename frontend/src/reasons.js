// Presentation metadata for backend reason codes. Meaning comes from the backend;
// this only decides the short badge text and colour family.
export const REASONS = {
  MISSING_IN_B: { short: "Missing in B", tone: "amber" },
  ORPHAN_IN_B: { short: "Orphan in B", tone: "violet" },
  DUPLICATE_IN_B: { short: "Duplicate in B", tone: "orange" },
  VALUE_MISMATCH: { short: "Value mismatch", tone: "red" },
  UNPARSEABLE_VALUE: { short: "Invalid value", tone: "rose" },
  DATE_MISMATCH: { short: "Date mismatch", tone: "blue" },
  LOCATION_MISMATCH: { short: "Location mismatch", tone: "blue" },
  CATEGORY_MISMATCH: { short: "Category mismatch", tone: "blue" },
  VOIDED_IN_A: { short: "Voided in A", tone: "slate" },
  DUPLICATE_IN_A: { short: "Duplicate in A", tone: "orange" },
  CROSS_TENANT: { short: "Cross-tenant", tone: "slate" },
  UNKNOWN_LOCATION: { short: "Unknown location", tone: "slate" },
};

export const reasonMeta = (code) => REASONS[code] || { short: code, tone: "slate" };

// The headline categories from the brief, shown as summary cards.
export const SUMMARY_CARDS = [
  { code: "MISSING_IN_B", title: "Missing records", caption: "In A, no entry in B" },
  { code: "DUPLICATE_IN_B", title: "Duplicate entries", caption: "Entered into B more than once" },
  { code: "VALUE_MISMATCH", title: "Value mismatches", caption: "A and B report different values" },
  { code: "ORPHAN_IN_B", title: "Orphan entries", caption: "B points at no A record" },
];
