# ADOSX Data Reconciliation System

## 1. Project Overview

Two systems (A and B) record the same events. Neither one is the source of truth. This app imports both exports, finds the records where they disagree, and shows each organisation (tenant) only its own disagreements.

## 2. Key Features

- Imports the three CSV files into PostgreSQL without dropping any row
- Matches System B entries to System A records, even when references are messy
- Finds missing, orphan, duplicate and value-mismatch records (plus a few extra checks)
- Shows a table with the reason, both values, the difference and the location
- Filter by reason, sort by value
- Strict tenant isolation: ORG-A never sees ORG-B data, and vice versa

## 3. Technology Stack

| Part | Tools |
|---|---|
| Backend | Python, Django, Django REST Framework, psycopg |
| Database | PostgreSQL (tested on 17) |
| Frontend | React 18, Vite |
| Tests | Django test runner (on PostgreSQL), Vitest, Testing Library, jsdom |

## 4. Architecture

```
CSV files ──► importer ──► PostgreSQL ──► comparison engine ──► discrepancies table
                                                                       │
                       React table ◄── REST API (tenant-scoped) ◄──────┘
```

1. `import_data` loads the CSVs, then runs the comparison and saves the results.
2. The API returns only the disagreements of the tenant making the request.
3. The React page displays them.

## 5. Project Structure

```
backend/
  config/                  Django settings and URLs
  recon/
    models.py              Database tables
    normalize.py           Parses references, numbers and dates
    importer.py            CSV → database
    reconcile.py           Comparison rules (pure Python, no database)
    services.py            Runs the comparison and saves the results
    tenancy.py             Decides which tenant a request belongs to
    views.py, urls.py      API endpoints
    management/commands/import_data.py
    tests/                 Backend tests
frontend/
  src/App.jsx              The page
  src/api.js               API calls
  src/format.js            How values, blanks and differences are shown
data/                      Put the CSV files here (not committed)
docker-compose.yml         Optional local PostgreSQL
DECISIONS.md               Key design decisions
```

## 6. Database Design

| Table | Holds |
|---|---|
| `Org` | One row per organisation (tenant) |
| `Location` | Each location and the org it belongs to (from `locations.csv`) |
| `SystemARecord` | One row per line of `system_a.csv` |
| `SystemBEntry` | One row per line of `system_b.csv` |
| `Discrepancy` | One row per disagreement found |
| `ImportRun` | One row per import, with row counts and every parse problem |

- Every imported row keeps the **original CSV line** (`raw`) next to the cleaned values.
- A value that can't be read is stored as empty (NULL), with a note saying why.
- Every A record, B entry and discrepancy stores its `org`, taken from its location. This makes filtering by tenant simple and safe.

## 7. How Data Reconciliation Works

1. **Split by organisation.** Each row's org comes from its location in `locations.csv`.
2. **Clean the reference.** `rec1034`, ` REC - 1070 ` and `1112` become `REC-1034`, `REC-1070` and `REC-1112`.
3. **Match inside the same org only.** Each A record is paired with the B entries that point at it.
4. **Compare.** B's value is compared with A's `total_value`, exactly to the cent.

**The four required checks**

| Reason | Meaning |
|---|---|
| Missing in B | A record has no B entry |
| Orphan in B | A B entry points at a record that doesn't exist |
| Duplicate in B | Several B entries for one record, and they don't add up to A's value |
| Value mismatch | A and B report different values |

**Split vs duplicate:** if several B entries **add up exactly** to A's value, it's a split, not an error (REC-1055). If they don't, it's a duplicate (REC-1042).

**Extra checks:** invalid/blank value, date mismatch, location mismatch (same org), category mismatch, voided in A but live in B.

**Results on the supplied data**

| Org | Reason | Records |
|---|---|---|
| ORG-A | Missing in B | REC-1015, REC-1077 |
| ORG-A | Orphan in B | REC-1999 |
| ORG-A | Duplicate in B | REC-1042 |
| ORG-A | Value mismatch | REC-1027, REC-1064, REC-1088 |
| ORG-B | Missing in B | REC-1061 |
| ORG-B | Orphan in B | REC-1077 (its entry) |
| ORG-B | Value mismatch | REC-1003 |
| ORG-B | Invalid value (blank) | REC-1050 |
| ORG-B | Date mismatch | REC-1009 |
| ORG-B | Voided in A | REC-1019 |

Not flagged, on purpose: REC-1055 (a valid split), and the three messy references, which match correctly.

## 8. Data Handling

| Problem | What happens |
|---|---|
| Blank value | Stored as empty with a note; shown as "(blank in System B)", never as 0 |
| Not a number | Stored as empty with a note; the original text is kept |
| Commas in numbers | Accepted as thousands separators: `"1,25,400.00"` → 125400.00. `"1.234,56"` is rejected, not guessed |
| Messy reference | Cleaned to `REC-<digits>`. Anything else is not guessed and becomes an orphan |
| Same record twice in B | Flagged as a duplicate unless the entries add up to A's value |
| Extra or missing columns | Row is still stored and flagged |
| Unknown location, or one claimed by two orgs | Row is stored but belongs to no tenant, so no one sees it |

On the supplied data: 5/5 locations, 120/120 A rows and 121/121 B rows stored. **0 rows dropped.**

## 9. Multi-Tenant Isolation

- **Matching never crosses orgs.** Rows are split by org first, so a result can't mix tenants.
- **The server decides the tenant.** The page asks the server for a signed tenant token, and every data request must carry it. The tenant is read from the token, never from the URL or a header.
- **Cross-tenant attempts are rejected.** No token or a fake token returns **401**. A valid token plus another org named in the request returns **403**.
- **Example, REC-1077:** an ORG-A record whose B entry sits at an ORG-B location. ORG-A sees "missing", ORG-B sees "orphan", and neither sees the other's data.
- **Limitation:** there is no login (out of scope). The organisation picker is a demo stand-in that can get a token for any org. Turn it off with `ADOSX_DEMO_TENANT_SWITCHING=0`. Real use would need an authenticated login in its place.

## 10. Prerequisites

- Python 3.11+
- Node.js 18+
- PostgreSQL 14+ (installed locally, or via Docker)

## 11. Installation and Setup

```bash
git clone https://github.com/UjwalAnanthula/ADOSX_Assignment.git
cd ADOSX_Assignment

# Backend
cd backend
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env              # then edit the values (see section 12)

# Frontend
cd ../frontend
npm ci
```

## 12. Environment Configuration

Copy `backend/.env.example` to `backend/.env`. `.env` is git-ignored.

| Variable | Default | Purpose |
|---|---|---|
| `POSTGRES_DB` | `adosx` | Database name |
| `POSTGRES_USER` | `adosx` | Database user |
| `POSTGRES_PASSWORD` | (empty) | Database password |
| `POSTGRES_HOST` | `localhost` | Database host |
| `POSTGRES_PORT` | `5432` | Database port |
| `DJANGO_DEBUG` | `1` | Set `0` outside development |
| `DJANGO_SECRET_KEY` | random in dev | Signs tenant tokens. **Required** when `DJANGO_DEBUG=0` |
| `ADOSX_DEMO_TENANT_SWITCHING` | same as `DJANGO_DEBUG` | Enables the demo organisation picker |
| `TENANT_CONTEXT_MAX_AGE` | `28800` | Tenant token lifetime in seconds |
| `ADOSX_DATA_DIR` | `data/` | Where the CSV files are |

## 13. Database Setup

**Option A: your own PostgreSQL**
```sql
CREATE ROLE adosx LOGIN PASSWORD 'choose-one' CREATEDB;   -- CREATEDB is needed for tests
CREATE DATABASE adosx OWNER adosx;
```

**Option B: Docker**
```bash
docker compose up -d      # uses the values in backend/.env
```
If port 5432 is busy, start it on another port (e.g. `POSTGRES_PORT=55432 docker compose up -d`) and set the same port in `backend/.env`.

**Then create the tables:**
```bash
cd backend
python manage.py migrate
```

## 14. Data Import

The assignment CSV files are not in this repository. Copy them into `data/`:
```
data/system_a.csv
data/system_b.csv
data/locations.csv
```
Then run:
```bash
cd backend
python manage.py import_data                   # add --verbose-issues to see every note
```
It prints rows read and stored per file, and the disagreements found. Running it again is safe: it replaces the previous import.

## 15. Running the Application

```bash
# Terminal 1
cd backend
python manage.py runserver                     # API on http://127.0.0.1:8000

# Terminal 2
cd frontend
npm run dev                                    # open http://localhost:5173
```

## 16. Running Tests

```bash
cd backend && python manage.py test recon      # 57 tests, needs PostgreSQL
cd frontend && npm test                        # 14 tests
```

| Test file | Covers |
|---|---|
| `test_reconcile.py` | One test per disagreement type, split entries, messy references, blank and invalid values |
| `test_import_and_api.py` | No rows dropped, raw values kept, repeat import, filtering, sorting |
| `test_tenant_security.py` | Cross-tenant attacks: fake or expired tokens, wrong org in the request, contested locations |
| `test_assignment_dataset.py` | Exact results on the real CSVs (skipped if they're not in `data/`) |
| `App.test.jsx`, `format.test.js` | Tenant token use, org switch, filters, sorting, blank values, error and retry |

## 17. What Was Deliberately Not Built

- **Login / authentication:** out of scope per the brief. A demo tenant picker stands in for it.
- **Advanced dashboards, charts, visual polish:** a clear table is enough.
- **Performance work and pagination:** each file has about 120 rows.
- **Fuzzy reference matching:** unclear references are reported, not guessed.
- **A screen for import problems:** they are printed by `import_data` and stored in `ImportRun`.

**Known limitations**
- If two genuinely duplicated entries happen to add up to A's value, they would pass as a split.
- The demo tenant picker lets anyone pick any org (see section 9).

## 18. How I Worked with the Agent

> **[YOUR INPUT NEEDED]** In your own words: what you asked the agent (Claude Code) to do, what you checked yourself, and what you changed. Only claim what you did; you'll be asked to defend this code.

Facts from the build you can check in `git log` and use:
- The agent read the brief and every CSV row before writing code, and listed the problems it found.
- The comparison rules were kept in one pure module (`reconcile.py`) so they could be tested without a database.
- Tests were run on PostgreSQL and on the real data, and the page was checked in a browser.
- The first tenant design trusted a header the browser could change. It was found and replaced with server-signed tenant tokens.

## 19. Assignment Questions

**a. Name one thing the AI agent got wrong. How did you notice?**
> **[YOUR INPUT NEEDED]** Candidates, verify before using:
> - The number parser read `"1.234,56"` as `1.23456` while its own comment said it would reject it. A unit test failed and caught it.
> - The first version trusted an `X-Org-Id` header for the tenant, so any caller could read any org's data by changing it.

**b. Which part of your submission are you least confident about, and why?**
> **[YOUR INPUT NEEDED]** Candidates: how REC-1077 is shown to each tenant, and whether "voided in A" should count as a disagreement. The brief doesn't settle either one.

**c. If you had a second day, what would you fix first?**
> **[YOUR INPUT NEEDED]** Candidates: replace the demo tenant picker with real login, and add a screen for import problems.
