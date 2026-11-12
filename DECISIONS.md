# Decisions

### 1. Match records only inside the same organisation
- **Decision:** Split all rows by organisation first, then match. A location claimed by two organisations belongs to neither.
- **Rejected:** Match everything together, then filter the results by organisation.
- **Why:** If matching never crosses organisations, a result can't leak another organisation's data, even if there's a bug later.

### 2. REC-1077: show each organisation only its own side
- **Decision:** The record's organisation (ORG-A) sees "missing"; the entry's organisation (ORG-B) sees "orphan". Only the operator sees the link.
- **Rejected:** Show both organisations a "cross-organisation" row.
- **Why:** Telling ORG-A about ORG-B's entry would show ORG-A data that isn't theirs.

### 3. Split or duplicate? Check whether the entries add up
- **Decision:** Several B entries for one record are a split if they add up exactly to A's value; otherwise they're a duplicate.
- **Rejected:** Call every repeated record a duplicate, or trust labels like "part 2 of 2".
- **Why:** One simple rule handles both REC-1055 (split) and REC-1042 (duplicate), and labels are free text.

### 4. Keep every row, even broken ones
- **Decision:** Save the original CSV line with every row. A value that can't be read is saved as empty, with a note saying why.
- **Rejected:** Skip bad rows, or turn bad values into 0.
- **Why:** The brief says never drop rows silently, and an empty value with a reason is honest; a 0 would be a lie.

### 5. Clean references with one strict rule, never guess
- **Decision:** `rec1034`, ` REC - 1070 ` and `1112` become `REC-xxxx`. Anything else is left unmatched.
- **Rejected:** Fuzzy matching ("looks similar to REC-1034").
- **Why:** A wrong match would hide a real problem; an unmatched reference shows up as an orphan someone can check.

### 6. Compare money exactly, to the cent
- **Decision:** Use `Decimal`, compare B's value with A's `total_value`, and allow commas only as thousands separators.
- **Rejected:** `float`, a tolerance, or removing every comma.
- **Why:** Float makes cents unreliable, and removing every comma turned `"1.234,56"` into `1.23456` (a test caught it).

### 7. A record voided in A but still in B is a disagreement
- **Decision:** Flag REC-1019.
- **Rejected:** Ignore it because B has no status column.
- **Why:** A cancelled event still counted somewhere else is exactly what a reconciler wants to see. (It's a judgment call.)

### 8. The server decides the organisation, not the browser
- **Decision:** Each data request carries a server-signed token naming its organisation. Naming a different organisation in the request gets 403.
- **Rejected:** Trust an `X-Org-Id` header or `?org=` (the first version did, and anyone could read any organisation).
- **Why:** The browser can change anything it sends; a signed token can't be edited. Limit: without a login, the demo picker can still get a token for either organisation.

### 9. Store results at import time; re-import replaces everything
- **Decision:** Save the disagreements in a table when importing. A new import replaces the old one in a single step.
- **Rejected:** Recalculate on every page load, or update the old data piece by piece.
- **Why:** Filtering and sorting become simple database queries, and every import gives the same result.
