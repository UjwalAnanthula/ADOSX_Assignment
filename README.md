# ADOSX_Assignment
A Django and React application that compares records from two systems, detects missing, duplicate and mismatched entries, and ensures secure multi-tenant data isolation.

Imports two systems' exports of the same events, finds where they disagree, and shows each tenant (org) only its own disagreements.

**Stack:** Django 5/6 + Django REST Framework, PostgreSQL, React (Vite).

## Architecture

```
data/*.csv ──► importer.py ──► PostgreSQL (raw row + typed columns + parse_errors)
                                   │
                    services.py loads rows ─► reconcile.py (pure Python, no DB)
                                   │                 │
                                   ◄── Discrepancy rows (one org each, or NULL = operator-only)
                                   │
               DRF API (X-Org-Id required) ──► React table (filter by reason, sort by value)
```

| File | Role |
|---|---|
| `backend/recon/normalize.py` | Parsers for refs, money, dates. Each returns `(value, error)` |
| `backend/recon/importer.py` | CSV → DB. Every row stored; nothing coerced silently |
| `backend/recon/reconcile.py` | **The comparison rules.** Pure functions, per-tenant matching |
| `backend/recon/services.py` | Loads DB rows → `reconcile()` → saves `Discrepancy` rows |
| `backend/recon/views.py` | Tenant-scoped API |
| `frontend/src/App.jsx` | The table |

### Tables
- `Org`, `Location`: from `locations.csv`, the only source of location → org.
- `SystemARecord`, `SystemBEntry`: one row per CSV row. `raw` (JSON) holds the row exactly as read; typed columns are nullable; `parse_errors` says why a value is NULL or how a ref was normalised. `org` is denormalised from location, so tenant scoping is one indexed filter.
- `Discrepancy`: one disagreement with reason, both values, location, entry ids and detail. `org = NULL` means operator-only.
- `ImportRun`: audit row per import, with per-file `rows_read` / `rows_stored` and every row-level issue.

## Setup from a clean clone

Prerequisites: Python 3.11+, Node 18+, PostgreSQL 14+ (local install or Docker).

**1. Database.** Either use an existing PostgreSQL:
```sql
CREATE ROLE adosx LOGIN PASSWORD 'choose-one' CREATEDB;  -- CREATEDB lets the test runner create its test DB
CREATE DATABASE adosx OWNER adosx;
```
or start a throwaway one with Docker (uses the credentials from `backend/.env`):
```bash
cp backend/.env.example backend/.env      # then edit values
docker compose up -d                      # if 5432 is taken: set POSTGRES_PORT in a root .env or your shell
```

**2. Configure.** `cp backend/.env.example backend/.env` and set `POSTGRES_*`. Real environment variables override the file. `backend/.env` is git-ignored.

**3. Backend.**
```bash
cd backend
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
```

**4. Data.** The assignment CSVs are **not** in this repo (not ours to redistribute). Copy `system_a.csv`, `system_b.csv` and `locations.csv` into `data/`, then:
```bash
python manage.py import_data                    # --data-dir PATH to use another folder; --verbose-issues to list every note
python manage.py runserver                      # http://127.0.0.1:8000/api/
```
Re-running `import_data` is safe: it replaces the previous load in a single transaction.

**5. Frontend** (in a second terminal):
```bash
cd frontend
npm ci
npm run dev                                     # http://localhost:5173 (proxies /api to :8000)
```

### API
All tenant endpoints require the header `X-Org-Id: ORG-A` (400 without it, 404 if unknown).
- `GET /api/orgs/`: org ids (stands in for login in the demo UI)
- `GET /api/discrepancies/?reason=VALUE_MISMATCH&ordering=-b_value`: `ordering` ∈ `a_value, -a_value, b_value, -b_value` (nulls last)
- `GET /api/summary/`: counts per reason and import row counts for the tenant

## Tests
```bash
cd backend && python manage.py test recon       # needs PostgreSQL (and a role allowed to create the test DB)
cd frontend && npm test
```
- `test_reconcile.py`: the comparison rules. One test per disagreement kind, plus non-errors (split entry, messy refs, labels without a category), dirty values and the tenant boundary. No DB.
- `test_import_and_api.py`: against PostgreSQL with a synthetic dirty dataset. No row dropped, raw preserved, ragged rows, repeat import, tenant isolation over HTTP, filter and sort.
- `test_assignment_dataset.py`: exact expected discrepancy set for the real files. **Skipped** if `data/*.csv` are absent.

- `frontend/src/App.test.jsx`: every tenant request carries `X-Org-Id`, switching org clears the reason filter, blank B values never show as 0, header sort, error + Retry, unknown `?reason=` dropped. `format.test.js` covers value display and B − A in exact cents.

At the time of writing: 42 backend tests and 13 frontend tests pass.

## What it finds in the supplied data

Import: locations 5/5, system_a 120/120, system_b 121/121 rows stored. 0 rejected; 5 B rows carry import notes (3 normalised refs, 1 blank value, 1 Indian-format number).

| Org | Reason | Record | Why |
|---|---|---|---|
| ORG-A | MISSING_IN_B | REC-1015 | no B entry |
| ORG-A | MISSING_IN_B | REC-1077 | its B entry is filed under ORG-B's LOC-201 |
| ORG-A | ORPHAN_IN_B | REC-1999 | no such record |
| ORG-A | DUPLICATE_IN_B | REC-1042 | ENT/2026/4042 and ENT/2026/4902, same value twice |
| ORG-A | VALUE_MISMATCH | REC-1027, REC-1088 | B = A's base_value (adjustment missing) |
| ORG-A | VALUE_MISMATCH | REC-1064 | B `"1,25,400.00"` = 125,400.00 vs A 183,244.16 |
| ORG-B | MISSING_IN_B | REC-1061 | no B entry |
| ORG-B | ORPHAN_IN_B | REC-1077 | ENT/2026/4077 points at a record not in ORG-B |
| ORG-B | VALUE_MISMATCH | REC-1003 | B = A's base_value |
| ORG-B | UNPARSEABLE_VALUE | REC-1050 | B value blank |
| ORG-B | DATE_MISMATCH | REC-1009 | 03-31 vs 04-02 |
| ORG-B | VOIDED_IN_A | REC-1019 | voided in A, live in B |
| operator | CROSS_TENANT | REC-1077 | never served to a tenant |

**Not flagged, on purpose:** REC-1055 has two B entries (71,950.93 + 107,926.39 = 179,877.32 = A total). That's a split, not a duplicate. `rec1034`, ` REC - 1070 ` and `1112` match their records. The blank `actor_id` on REC-1050 in A is not a disagreement, since B has no actor field.

## What I built
- Raw-preserving importer with per-row parse notes and an import audit (`ImportRun`).
- Comparison engine: missing, orphan, duplicate, value, unparseable value, date, location, category (from B's label), voided, duplicate id in A, unknown location, cross-tenant.
- Tenant-scoped API and a plain table: reason filter, sort by A/B value (dropdown or column header), a B − A column, view state kept in the URL, and loading/empty/error-with-retry states.

## What I deliberately did not build
- Authentication (the brief says to skip it). The `X-Org-Id` header stands in for the session's org.
- A UI for import issues or operator-only findings. They are printed by `import_data` and stored in `ImportRun` / `Discrepancy(org=NULL)`.
- Checking A's internal arithmetic (`base + adjustment = total`). That's not a cross-system disagreement.
- Fuzzy reference matching, non-ISO dates, currency symbols. These are reported as unparseable rather than guessed.
- Pagination, performance work, visual design.

## Known limitations
- The split rule is "entries sum exactly to A's total". Two genuinely duplicated half-entries that happen to sum to the total would pass as a split.
- A record with several findings (e.g. value and date) shows as several rows. Sorting by value treats them independently.
- Re-import replaces everything; there's no history of past discrepancy sets beyond `ImportRun` stats.

## How I worked with the agent

> **[YOUR INPUT NEEDED]** Describe in your own words how you used the agent (Claude Code): what you asked it for, what you checked yourself, and what you changed. The interviewers will ask you to defend this code, so only claim what you did.

Facts from the build session you can verify and use (`git log` shows each step):
- The agent read the brief and every CSV row first and listed the anomalies before writing code.
- The comparison rules were written as a pure module (`reconcile.py`) so they could be tested without a database.
- Tests were run against PostgreSQL and the real dataset, and the UI was driven in a browser (switch org, filter, sort) to check it end to end.

## Questions

**a. Name one thing the AI agent got wrong. How did you notice?**
> **[YOUR INPUT NEEDED, in your own words.]** Candidate facts from this session (check them in the commit history before using):
> - `parse_money` stripped every comma before validating, so the European `"1.234,56"` was silently read as `1.23456`, while its own docstring claimed such input was rejected. A unit test listing bad inputs failed. Fixed in commit "Fix parse_money silently misreading…".
> - In its first manual read of the CSVs the agent listed two ORG-A value mismatches. The code found a third (REC-1088, B = base_value), confirmed by checking the row by hand. The manual read had been wrong, not the code.

**b. Which part of your submission are you least confident about, and why?**
> **[YOUR INPUT NEEDED.]** Candidates: the REC-1077 cross-tenant treatment (DECISIONS #2) and whether VOIDED-in-A should be a disagreement (DECISIONS #8). Both are judgment calls the brief doesn't settle.

**c. If you had a second day, what would you fix first?**
> **[YOUR INPUT NEEDED.]** Candidates: show import issues and operator-only findings in the UI, and make the split-vs-duplicate rule stricter (e.g. also require distinct entry ids and labels).
