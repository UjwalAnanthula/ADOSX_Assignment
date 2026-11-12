"""
The comparison logic: decides which records disagree and why.

Pure Python, no Django, so it can be tested without a database.

Tenant safety is structural, not a filter applied afterwards: rows are first
split by org, and matching only ever happens *inside* one org's bucket. A
finding produced for org X is built only from org X's rows, so it cannot
contain another tenant's data. References that cross the org boundary are
detected in a separate pass and emitted with org=None (operator-only).
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .normalize import category_from_label

# Reason codes. Mirrors models.Discrepancy.Reason; plain strings so this
# module has no Django dependency.
MISSING_IN_B = "MISSING_IN_B"
ORPHAN_IN_B = "ORPHAN_IN_B"
DUPLICATE_IN_B = "DUPLICATE_IN_B"
VALUE_MISMATCH = "VALUE_MISMATCH"
UNPARSEABLE_VALUE = "UNPARSEABLE_VALUE"
DATE_MISMATCH = "DATE_MISMATCH"
LOCATION_MISMATCH = "LOCATION_MISMATCH"
CATEGORY_MISMATCH = "CATEGORY_MISMATCH"
VOIDED_IN_A = "VOIDED_IN_A"
DUPLICATE_IN_A = "DUPLICATE_IN_A"
CROSS_TENANT = "CROSS_TENANT"
UNKNOWN_LOCATION = "UNKNOWN_LOCATION"


@dataclass(frozen=True)
class ARecord:
    record_id: str
    org_id: str | None
    location_id: str | None
    total_value: Decimal | None
    event_date: date | None = None
    category_code: str = ""
    base_value: Decimal | None = None
    state: str = "CONFIRMED"
    raw_total_value: str = ""


@dataclass(frozen=True)
class BEntry:
    entry_id: str
    ref: str | None  # normalised record_ref; None if unrecognisable
    org_id: str | None
    location_id: str | None
    value: Decimal | None
    recorded_on: date | None = None
    label: str = ""
    raw_ref: str = ""
    raw_value: str = ""


@dataclass
class Finding:
    reason: str
    org_id: str | None
    record_id: str = ""
    entry_ids: list = field(default_factory=list)
    location_id: str = ""
    a_value: Decimal | None = None
    b_value: Decimal | None = None
    b_raw_value: str = ""
    detail: str = ""


def reconcile(a_records, b_entries):
    """Return every disagreement between System A records and System B entries."""
    a_by_org = defaultdict(list)
    b_by_org = defaultdict(list)
    for a in a_records:
        a_by_org[a.org_id].append(a)
    for b in b_entries:
        b_by_org[b.org_id].append(b)

    findings = []
    for org_id in sorted(set(a_by_org) | set(b_by_org), key=lambda o: o or ""):
        tenant_findings = _reconcile_one_org(a_by_org[org_id], b_by_org[org_id])
        for f in tenant_findings:
            # Rows with an unknown location have no tenant: operator-only.
            f.org_id = org_id
        findings += tenant_findings
    findings += _operator_findings(a_records, b_entries)
    return findings


def _reconcile_one_org(a_records, b_entries):
    findings = []

    a_by_id = defaultdict(list)
    for a in a_records:
        a_by_id[a.record_id].append(a)
    b_by_ref = defaultdict(list)
    for b in b_entries:
        b_by_ref[b.ref].append(b)

    # A record_id seen twice in A: flag it, then compare using the first occurrence.
    for record_id, dupes in a_by_id.items():
        if len(dupes) > 1:
            findings.append(Finding(
                DUPLICATE_IN_A, None, record_id=record_id, location_id=dupes[0].location_id or "",
                a_value=dupes[0].total_value,
                detail=f"record_id appears {len(dupes)} times in System A",
            ))

    for record_id, dupes in a_by_id.items():
        findings += _compare_record(dupes[0], b_by_ref.get(record_id, []))

    # B entries whose ref resolves to nothing in this org.
    for ref, entries in b_by_ref.items():
        if ref is not None and ref in a_by_id:
            continue
        for b in entries:
            why = (f"Reference {b.raw_ref!r} is not a recognisable record id" if ref is None
                   else f"{ref} not found in System A for this organisation")
            findings.append(Finding(
                ORPHAN_IN_B, None, record_id=ref or "", entry_ids=[b.entry_id],
                location_id=b.location_id or "", b_value=b.value, b_raw_value=b.raw_value, detail=why,
            ))
    return findings


def _compare_record(a, entries):
    """All disagreements between one A record and the B entries that point at it."""
    def finding(reason, **kw):
        kw.setdefault("location_id", a.location_id or "")
        kw.setdefault("a_value", a.total_value)
        kw.setdefault("entry_ids", [e.entry_id for e in entries])
        return Finding(reason, None, record_id=a.record_id, **kw)

    if not entries:
        return [finding(MISSING_IN_B, detail="No System B entry for this record within this organisation")]

    out = []
    if a.state.strip().upper() == "VOIDED":
        out.append(finding(VOIDED_IN_A, b_value=_sum(entries),
                           detail="System A marks this VOIDED; System B still carries it"))

    out += _compare_values(a, entries, finding)

    dates = {e.recorded_on for e in entries}
    if dates != {a.event_date}:
        out.append(finding(DATE_MISMATCH, b_value=_sum(entries),
                           detail=f"A: {a.event_date}  B: {', '.join(sorted(str(d) for d in dates))}"))

    # Only same-org locations can reach here (cross-org entries never match).
    other_locs = sorted({e.location_id or "?" for e in entries if e.location_id != a.location_id})
    if other_locs:
        out.append(finding(LOCATION_MISMATCH, b_value=_sum(entries),
                           detail=f"A: {a.location_id}  B: {', '.join(other_locs)}"))

    b_cats = {category_from_label(e.label) for e in entries} - {None}
    if a.category_code and b_cats and b_cats != {a.category_code}:
        out.append(finding(CATEGORY_MISMATCH, b_value=_sum(entries),
                           detail=f"A: {a.category_code}  B label: {', '.join(sorted(b_cats))}"))
    return out


def _compare_values(a, entries, finding):
    """Value rules, in order:

    1. Either side unparseable -> UNPARSEABLE_VALUE (can't compare; never guess).
    2. One entry            -> must equal A's total_value exactly (Decimal).
    3. Several entries      -> if they SUM to A's total it is a split entry,
                               which is NOT a disagreement. Otherwise the
                               record was entered twice -> DUPLICATE_IN_B.
    """
    if a.total_value is None:
        return [finding(UNPARSEABLE_VALUE, detail=f"System A total_value is {a.raw_total_value!r}")]
    bad = [e for e in entries if e.value is None]
    if bad:
        return [finding(UNPARSEABLE_VALUE, b_raw_value=bad[0].raw_value,
                        detail="System B value is " + ", ".join(f"{e.raw_value!r} ({e.entry_id})" for e in bad))]

    b_total = _sum(entries)
    if len(entries) == 1:
        if b_total == a.total_value:
            return []
        hint = ""
        if a.base_value is not None and b_total == a.base_value:
            hint = " (B equals A's base_value: adjustment missing in B)"
        return [finding(VALUE_MISMATCH, b_value=b_total, b_raw_value=entries[0].raw_value,
                        detail=f"B - A = {b_total - a.total_value}{hint}")]

    if b_total == a.total_value:
        return []  # split across several entries that add up: not a disagreement
    parts = ", ".join(f"{e.entry_id}={e.value}" for e in entries)
    return [finding(DUPLICATE_IN_B, b_value=b_total,
                    detail=f"{len(entries)} entries ({parts}) sum to {b_total}, not {a.total_value}")]


def _sum(entries):
    vals = [e.value for e in entries]
    return None if any(v is None for v in vals) else sum(vals, Decimal("0"))


def _operator_findings(a_records, b_entries):
    """Findings no tenant may see (org=None): they span or escape the org boundary."""
    out = []
    a_org_by_id = {a.record_id: a.org_id for a in a_records}
    for b in b_entries:
        a_org = a_org_by_id.get(b.ref)
        if b.ref is not None and a_org is not None and b.org_id is not None and a_org != b.org_id:
            out.append(Finding(
                CROSS_TENANT, None, record_id=b.ref, entry_ids=[b.entry_id], location_id=b.location_id or "",
                b_value=b.value, b_raw_value=b.raw_value,
                detail=f"B entry is under {b.org_id} ({b.location_id}); record belongs to {a_org}",
            ))
    for a in a_records:
        if a.org_id is None:
            out.append(Finding(UNKNOWN_LOCATION, None, record_id=a.record_id, location_id=a.location_id or "",
                               a_value=a.total_value, detail="System A location not in locations.csv"))
    for b in b_entries:
        if b.org_id is None:
            out.append(Finding(UNKNOWN_LOCATION, None, record_id=b.ref or "", entry_ids=[b.entry_id],
                               location_id=b.location_id or "", b_value=b.value, b_raw_value=b.raw_value,
                               detail="System B location not in locations.csv"))
    return out
