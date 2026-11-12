# Decisions

**1. Match inside each tenant; never across.**
Rejected: match globally on `record_ref`, then filter the results by org.
Why: if the split by org happens before matching, a tenant's result cannot contain another tenant's row, even when there's a bug further down. A filter applied afterwards is one forgotten `.filter()` away from a leak.

**2. A System B entry filed under another org's location (REC-1077) is shown as MISSING to the record's org, as ORPHAN to the entry's org, and as CROSS_TENANT to the operator only (`org = NULL`, never served by the API).**
Rejected: show a "cross-tenant" row to ORG-A or ORG-B.
Why: telling either tenant that the record or entry exists elsewhere already reveals the other tenant's data. Each tenant's view stays true from inside its own boundary, and the full diagnosis is printed by `import_data`.

**3. Several B entries for one record are a *split* if they sum exactly to A's `total_value`; otherwise they are a DUPLICATE_IN_B.**
Rejected: flag any record with more than one B entry as a duplicate, or rely on the label text ("part 2 of 2").
Why: the sum is a general rule that correctly clears REC-1055 and flags REC-1042 without hard-coding either, and labels are free text that can't be trusted.

**4. Store every CSV row as-is (`raw` JSON) next to nullable typed columns plus `parse_errors`.**
Rejected: reject rows that fail validation, or coerce bad values to 0 or blank.
Why: the brief forbids silently dropping rows, and a NULL with a recorded reason is honest where a 0 would lie. The importer reports `rows_read == rows_stored` per file.

**5. Normalise references only by a strict pattern (`REC-?digits`, ignoring case and whitespace), and keep the original.**
Rejected: fuzzy matching (edit distance, "contains 1034").
Why: a wrong match hides a real disagreement, while an unmatched ref shows up as an orphan a human can look at. All three dirty forms in the data (`rec1034`, ` REC - 1070 `, `1112`) fit the strict rule.

**6. Money is `Decimal`; commas are accepted only as digit-group separators (western and Indian lakh grouping), and `.` is the only decimal point.**
Rejected: `float`, or stripping every comma.
Why: `float` makes 0.01 differences unreliable. Stripping every comma silently turned `"1.234,56"` into `1.23456` (caught by a test, see README).

**7. Compare B's value with A's `total_value` and require exact equality.**
Rejected: compare with `base_value`, or allow a tolerance.
Why: on clean rows B equals `total_value` exactly. The mismatches where B equals `base_value` (REC-1003, 1027, 1088) are real disagreements, so they are flagged with a hint instead of being tolerated.

**8. Flag a record VOIDED in A that is still live in B (REC-1019) as a disagreement.**
Rejected: ignore it because B has no state column.
Why: a voided event still being counted elsewhere is exactly what someone reconciling would want to see. This is a judgment call and is listed as one in the README.

**9. No auth: the tenant comes from an `X-Org-Id` header, which the API requires (400 if missing, 404 if unknown).**
Rejected: an unscoped "all orgs" default, or tenant filtering in the frontend only.
Why: the brief says to skip auth, but the boundary must still be enforced server-side. Later, the header becomes the session's org and nothing else changes.

**10. Discrepancies are recomputed and stored at import time (one table), and re-import replaces everything in one transaction.**
Rejected: compute on every request, or upsert incrementally.
Why: a stored table makes "filter by reason / sort by value" a plain indexed query, and a full replace makes repeat imports deterministic.
