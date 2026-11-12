"""Glue between the database and the pure comparison logic in reconcile.py."""
from collections import Counter

from django.db import transaction

from .models import Discrepancy, SystemARecord, SystemBEntry
from .reconcile import ARecord, BEntry, reconcile


def _a_rows():
    for r in SystemARecord.objects.order_by("source_row"):
        yield ARecord(
            record_id=r.record_id, org_id=r.org_id, location_id=r.location_id or r.raw.get("location_id"),
            total_value=r.total_value, event_date=r.event_date, category_code=r.category_code,
            base_value=r.base_value, state=r.state, raw_total_value=r.raw.get("total_value") or "",
        )


def _b_rows():
    for e in SystemBEntry.objects.order_by("source_row"):
        yield BEntry(
            entry_id=e.entry_id, ref=e.record_ref, org_id=e.org_id,
            location_id=e.location_id or e.raw.get("location_id"), value=e.value,
            recorded_on=e.recorded_on, label=e.label, raw_ref=e.raw_record_ref,
            raw_value=e.raw.get("value") or "",
        )


@transaction.atomic
def rebuild_discrepancies():
    """Recompute every discrepancy from the stored rows. Deterministic; returns counts by (org, reason)."""
    findings = reconcile(list(_a_rows()), list(_b_rows()))
    Discrepancy.objects.all().delete()
    Discrepancy.objects.bulk_create(
        Discrepancy(
            org_id=f.org_id, reason=f.reason, record_id=f.record_id, entry_ids=f.entry_ids,
            location_id=f.location_id, a_value=f.a_value, b_value=f.b_value,
            b_raw_value=f.b_raw_value or "", detail=f.detail,
        )
        for f in findings
    )
    return Counter((f.org_id or "(operator only)", f.reason) for f in findings)
