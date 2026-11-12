"""
Tables.

Every imported table keeps the original CSV row verbatim in `raw` alongside
typed, *nullable* parsed columns. A value that fails to parse becomes NULL
plus a note in `parse_errors`; the row itself is always stored. That is how
the importer "survives" dirty data without silently dropping anything.

`org` is denormalised onto every tenant-owned row (derived from location at
import time) so that tenant scoping is a single indexed filter, not a join
someone can forget.
"""
from django.db import models


class ImportRun(models.Model):
    """Audit trail: one row per `import_data` run, with per-file counts and every parse issue."""
    created_at = models.DateTimeField(auto_now_add=True)
    stats = models.JSONField(default=dict)


class Org(models.Model):
    org_id = models.CharField(primary_key=True, max_length=32)

    def __str__(self):
        return self.org_id


class Location(models.Model):
    location_id = models.CharField(primary_key=True, max_length=32)
    org = models.ForeignKey(Org, on_delete=models.PROTECT, related_name="locations")
    name = models.CharField(max_length=128, blank=True)


class SystemARecord(models.Model):
    source_row = models.PositiveIntegerField(help_text="1-based line number in system_a.csv")
    raw = models.JSONField(help_text="The CSV row exactly as read")
    parse_errors = models.JSONField(default=list)

    # Not unique: a duplicated record_id in an export must be stored and flagged, not crash the import.
    record_id = models.CharField(max_length=64, db_index=True)
    location = models.ForeignKey(Location, null=True, on_delete=models.SET_NULL)
    org = models.ForeignKey(Org, null=True, on_delete=models.SET_NULL, db_index=True)
    event_date = models.DateField(null=True)
    category_code = models.CharField(max_length=32, blank=True)
    actor_id = models.CharField(max_length=32, blank=True)
    base_value = models.DecimalField(max_digits=14, decimal_places=2, null=True)
    adjustment = models.DecimalField(max_digits=14, decimal_places=2, null=True)
    total_value = models.DecimalField(max_digits=14, decimal_places=2, null=True)
    state = models.CharField(max_length=32, blank=True)


class SystemBEntry(models.Model):
    source_row = models.PositiveIntegerField(help_text="1-based line number in system_b.csv")
    raw = models.JSONField(help_text="The CSV row exactly as read")
    parse_errors = models.JSONField(default=list)

    entry_id = models.CharField(max_length=64, db_index=True)
    raw_record_ref = models.CharField(max_length=64, blank=True)
    # Canonical form, e.g. "REC-1034". NULL when the ref is unrecognisable.
    record_ref = models.CharField(max_length=64, null=True, db_index=True)
    location = models.ForeignKey(Location, null=True, on_delete=models.SET_NULL)
    org = models.ForeignKey(Org, null=True, on_delete=models.SET_NULL, db_index=True)
    recorded_on = models.DateField(null=True)
    value = models.DecimalField(max_digits=14, decimal_places=2, null=True)
    label = models.CharField(max_length=128, blank=True)


class Reason(models.TextChoices):
    MISSING_IN_B = "MISSING_IN_B", "Record has no entry in System B"
    ORPHAN_IN_B = "ORPHAN_IN_B", "System B entry points at a record that does not exist"
    DUPLICATE_IN_B = "DUPLICATE_IN_B", "Record entered into System B more than once"
    VALUE_MISMATCH = "VALUE_MISMATCH", "Systems report different values"
    UNPARSEABLE_VALUE = "UNPARSEABLE_VALUE", "Value missing or not a number"
    DATE_MISMATCH = "DATE_MISMATCH", "Systems report different dates"
    LOCATION_MISMATCH = "LOCATION_MISMATCH", "Systems report different locations"
    CATEGORY_MISMATCH = "CATEGORY_MISMATCH", "Systems report different categories"
    VOIDED_IN_A = "VOIDED_IN_A", "Voided in System A but live in System B"
    DUPLICATE_IN_A = "DUPLICATE_IN_A", "record_id appears more than once in System A"
    CROSS_TENANT = "CROSS_TENANT", "System B entry filed under another org's location"
    UNKNOWN_LOCATION = "UNKNOWN_LOCATION", "Location not in locations.csv"


class Discrepancy(models.Model):
    """One disagreement between the systems, already scoped to a single tenant.

    org=NULL means operator-only (e.g. a cross-tenant reference): the tenant
    API never serves these.
    """

    Reason = Reason

    org = models.ForeignKey(Org, null=True, on_delete=models.CASCADE, db_index=True)
    reason = models.CharField(max_length=32, choices=Reason.choices, db_index=True)
    record_id = models.CharField(max_length=64, blank=True)
    entry_ids = models.JSONField(default=list)
    location_id = models.CharField(max_length=32, blank=True)
    a_value = models.DecimalField(max_digits=14, decimal_places=2, null=True)
    b_value = models.DecimalField(max_digits=14, decimal_places=2, null=True)
    b_raw_value = models.CharField(max_length=64, blank=True)
    detail = models.TextField(blank=True)

    class Meta:
        indexes = [models.Index(fields=["org", "reason"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(reason__in=Reason.values), name="discrepancy_reason_valid"
            ),
        ]
