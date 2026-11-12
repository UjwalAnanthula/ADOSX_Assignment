"""
CSV -> database. Knows nothing about comparison.

Contract: every data row in every file becomes exactly one database row.
Fields that fail to parse are stored as NULL with a reason in `parse_errors`,
and the untouched CSV row is kept in `raw`. The returned stats prove the
contract (rows_read == rows_stored) and are persisted on an ImportRun.

Re-running is safe: the import replaces the previous load inside a single
transaction, so it is all-or-nothing and the result is the same every time.
"""
import csv
from pathlib import Path

from django.db import transaction

from .models import Discrepancy, ImportRun, Location, Org, SystemARecord, SystemBEntry
from .normalize import normalize_ref, parse_date, parse_money

EXTRA = "_extra_columns"


def _read_csv(path):
    """Yield (line_number, raw_dict). utf-8-sig strips a BOM if present.
    Short rows get None for missing columns, long rows keep the extras under EXTRA."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh, restkey=EXTRA)
        for row in reader:
            yield reader.line_num, row


def _clean(value):
    return (value or "").strip() if isinstance(value, str) or value is None else value


def _shape_errors(raw):
    errors = []
    if raw.get(EXTRA):
        errors.append(f"row has {len(raw[EXTRA])} extra column(s)")
    missing = [k for k, v in raw.items() if v is None]
    if missing:
        errors.append(f"row is missing column(s): {', '.join(missing)}")
    return errors


def _resolve_location(raw_location_id, locations, errors):
    location = locations.get(_clean(raw_location_id))
    if location is None:
        errors.append(f"location_id {raw_location_id!r} not in locations.csv")
    return location


def _money(raw, column, errors):
    value, err = parse_money(raw.get(column))
    if err:
        errors.append(f"{column}: {err}")
    elif "," in (raw.get(column) or ""):
        errors.append(f"{column}: {raw.get(column)!r} read as {value}")  # informational, still traceable
    return value


def _date(raw, column, errors):
    value, err = parse_date(raw.get(column))
    if err:
        errors.append(f"{column}: {err}")
    return value


def _import_locations(path, stats):
    orgs, locations = {}, {}
    for line, raw in _read_csv(path):
        stats["rows_read"] += 1
        org_id, loc_id = _clean(raw.get("org_id")), _clean(raw.get("location_id"))
        if not org_id or not loc_id:
            # A location without an org cannot be owned by any tenant; report it loudly.
            stats["issues"].append({"line": line, "errors": ["location_id or org_id blank: row rejected"], "raw": raw})
            continue
        org = orgs.get(org_id) or Org.objects.create(org_id=org_id)
        orgs[org_id] = org
        locations[loc_id] = Location.objects.create(location_id=loc_id, org=org, name=_clean(raw.get("location_name")))
        stats["rows_stored"] += 1
    return locations


def _import_system_a(path, locations, stats):
    rows = []
    for line, raw in _read_csv(path):
        stats["rows_read"] += 1
        errors = _shape_errors(raw)
        location = _resolve_location(raw.get("location_id"), locations, errors)
        rows.append(SystemARecord(
            source_row=line, raw=raw,
            record_id=_clean(raw.get("record_id")),
            location=location, org=location.org if location else None,
            event_date=_date(raw, "event_date", errors),
            category_code=_clean(raw.get("category_code")),
            actor_id=_clean(raw.get("actor_id")),
            base_value=_money(raw, "base_value", errors),
            adjustment=_money(raw, "adjustment", errors),
            total_value=_money(raw, "total_value", errors),
            state=_clean(raw.get("state")).upper(),
            parse_errors=errors,
        ))
        if not _clean(raw.get("record_id")):
            errors.append("record_id blank")
        if errors:
            stats["issues"].append({"line": line, "errors": errors})
    SystemARecord.objects.bulk_create(rows)
    stats["rows_stored"] += len(rows)


def _import_system_b(path, locations, stats):
    rows = []
    for line, raw in _read_csv(path):
        stats["rows_read"] += 1
        errors = _shape_errors(raw)
        location = _resolve_location(raw.get("location_id"), locations, errors)
        raw_ref = raw.get("record_ref") or ""
        ref = normalize_ref(raw_ref)
        if ref is None:
            errors.append(f"record_ref {raw_ref!r} is not a recognisable record id")
        elif ref != raw_ref:
            errors.append(f"record_ref {raw_ref!r} normalised to {ref!r}")  # informational, still traceable
        rows.append(SystemBEntry(
            source_row=line, raw=raw,
            entry_id=_clean(raw.get("entry_id")),
            raw_record_ref=raw_ref, record_ref=ref,
            location=location, org=location.org if location else None,
            recorded_on=_date(raw, "recorded_on", errors),
            value=_money(raw, "value", errors),
            label=_clean(raw.get("label")),
            parse_errors=errors,
        ))
        if errors:
            stats["issues"].append({"line": line, "errors": errors})
    SystemBEntry.objects.bulk_create(rows)
    stats["rows_stored"] += len(rows)


@transaction.atomic
def import_all(data_dir):
    """Replace the current load with the three CSVs in `data_dir`. Returns the ImportRun."""
    data_dir = Path(data_dir)
    files = {name: data_dir / f"{name}.csv" for name in ("locations", "system_a", "system_b")}
    missing = [str(p) for p in files.values() if not p.exists()]
    if missing:
        raise FileNotFoundError(f"Missing input file(s): {', '.join(missing)}")

    for model in (Discrepancy, SystemBEntry, SystemARecord, Location, Org):
        model.objects.all().delete()

    stats = {name: {"rows_read": 0, "rows_stored": 0, "issues": []} for name in files}
    locations = _import_locations(files["locations"], stats["locations"])
    _import_system_a(files["system_a"], locations, stats["system_a"])
    _import_system_b(files["system_b"], locations, stats["system_b"])
    return ImportRun.objects.create(stats=stats)
