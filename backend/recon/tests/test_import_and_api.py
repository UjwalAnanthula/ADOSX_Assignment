"""
Integration tests against PostgreSQL: importer integrity, repeat imports,
tenant isolation through the HTTP API. Uses a small synthetic dirty dataset
written to a temp dir, so the suite runs from a clean clone without the
(non-redistributed) assignment files.
"""
import tempfile
from pathlib import Path

from django.test import TestCase
from rest_framework.test import APIClient

from recon.importer import import_all
from recon.models import Discrepancy, SystemARecord, SystemBEntry
from recon.services import rebuild_discrepancies

LOCATIONS = """location_id,org_id,location_name
LOC-101,ORG-A,Location 101
LOC-201,ORG-B,Location 201
"""
SYSTEM_A = """record_id,location_id,event_date,category_code,actor_id,base_value,adjustment,total_value,state
REC-1,LOC-101,2026-03-01,CAT-01,USR-1,80.00,20.00,100.00,CONFIRMED
REC-2,LOC-101,2026-03-01,CAT-01,,80.00,20.00,100.00,CONFIRMED
REC-3,LOC-101,2026-03-01,CAT-01,USR-1,80.00,20.00,100.00,CONFIRMED
REC-4,LOC-201,2026-03-01,CAT-01,USR-2,80.00,20.00,"1,000.00",CONFIRMED
REC-5,LOC-201,not-a-date,CAT-01,USR-2,abc,20.00,,CONFIRMED
REC-6,LOC-999,2026-03-01,CAT-01,USR-2,80.00,20.00,100.00,CONFIRMED
"""
SYSTEM_B = """entry_id,record_ref,location_id,recorded_on,value,label
E1, rec - 1 ,LOC-101,2026-03-01,100.00,Entry for CAT-01
E2,2,LOC-101,2026-03-01,,Entry for CAT-01
E3,REC-3,LOC-201,2026-03-01,100.00,Entry for CAT-01
E4,REC-4,LOC-201,2026-03-01,"1,000.00",Entry for CAT-01
E5,???,LOC-201,2026-03-01,12,Entry for CAT-01
E6,REC-404,LOC-201,2026-03-01,12,Entry for CAT-01,EXTRA
E7,REC-4,LOC-201
"""


class ImportedDataTestCase(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        (d / "locations.csv").write_text(LOCATIONS)
        (d / "system_a.csv").write_text(SYSTEM_A)
        (d / "system_b.csv").write_text(SYSTEM_B)
        self.data_dir = d
        self.run = import_all(d)
        rebuild_discrepancies()
        self.client = APIClient()

    def tearDown(self):
        self.tmp.cleanup()

    def get(self, org, **params):
        headers = {"HTTP_X_ORG_ID": org} if org else {}
        return self.client.get("/api/discrepancies/", params, **headers)


class ImporterTests(ImportedDataTestCase):
    def test_no_row_is_dropped(self):
        for name in ("system_a", "system_b", "locations"):
            s = self.run.stats[name]
            self.assertEqual(s["rows_read"], s["rows_stored"], name)
        self.assertEqual(SystemARecord.objects.count(), 6)
        self.assertEqual(SystemBEntry.objects.count(), 7)

    def test_raw_values_preserved_when_parsing_fails(self):
        rec5 = SystemARecord.objects.get(record_id="REC-5")
        self.assertIsNone(rec5.total_value)
        self.assertIsNone(rec5.base_value)
        self.assertIsNone(rec5.event_date)
        self.assertEqual(rec5.raw["base_value"], "abc")
        self.assertTrue(any("base_value" in e for e in rec5.parse_errors))

    def test_reference_normalised_without_losing_original(self):
        e1 = SystemBEntry.objects.get(entry_id="E1")
        self.assertEqual((e1.record_ref, e1.raw_record_ref), ("REC-1", " rec - 1 "))
        self.assertIsNone(SystemBEntry.objects.get(entry_id="E5").record_ref)

    def test_ragged_rows_are_stored_and_flagged(self):
        self.assertTrue(any("extra column" in e for e in SystemBEntry.objects.get(entry_id="E6").parse_errors))
        self.assertTrue(any("missing column" in e for e in SystemBEntry.objects.get(entry_id="E7").parse_errors))

    def test_unknown_location_row_kept_without_tenant(self):
        rec6 = SystemARecord.objects.get(record_id="REC-6")
        self.assertIsNone(rec6.org)
        self.assertEqual(rec6.raw["location_id"], "LOC-999")

    def test_repeat_import_is_idempotent(self):
        before = sorted(Discrepancy.objects.values_list("org", "reason", "record_id"), key=str)
        import_all(self.data_dir)
        rebuild_discrepancies()
        self.assertEqual(SystemARecord.objects.count(), 6)
        self.assertEqual(SystemBEntry.objects.count(), 7)
        self.assertEqual(sorted(Discrepancy.objects.values_list("org", "reason", "record_id"), key=str), before)


class TenantIsolationApiTests(ImportedDataTestCase):
    def test_org_header_required(self):
        self.assertEqual(self.get(None).status_code, 400)
        self.assertEqual(self.client.get("/api/summary/").status_code, 400)

    def test_unknown_org_rejected(self):
        self.assertEqual(self.get("ORG-Z").status_code, 404)

    def test_each_org_sees_only_its_own_rows(self):
        own_locations = {"ORG-A": {"LOC-101"}, "ORG-B": {"LOC-201"}}
        for org, locs in own_locations.items():
            rows = self.get(org).json()
            self.assertTrue(rows, org)
            self.assertTrue({row["location_id"] for row in rows} <= locs, org)

    def test_cross_tenant_entry_does_not_leak(self):
        # REC-3 is ORG-A's; its B entry E3 was filed under ORG-B's LOC-201.
        org_a = self.get("ORG-A").json()
        org_b = self.get("ORG-B").json()
        self.assertNotIn("E3", [e for row in org_a for e in row["entry_ids"]])
        self.assertIn({"reason": "MISSING_IN_B", "record_id": "REC-3"},
                      [{"reason": x["reason"], "record_id": x["record_id"]} for x in org_a])
        e3_rows = [x for x in org_b if "E3" in x["entry_ids"]]
        self.assertEqual([x["reason"] for x in e3_rows], ["ORPHAN_IN_B"])
        self.assertIsNone(e3_rows[0]["a_value"])

    def test_operator_only_findings_never_served(self):
        self.assertTrue(Discrepancy.objects.filter(org__isnull=True).exists())
        served = {x["id"] for org in ("ORG-A", "ORG-B") for x in self.get(org).json()}
        operator = set(Discrepancy.objects.filter(org__isnull=True).values_list("id", flat=True))
        self.assertFalse(served & operator)


class FilterSortApiTests(ImportedDataTestCase):
    def test_filter_by_reason(self):
        rows = self.get("ORG-B", reason="ORPHAN_IN_B").json()
        self.assertTrue(rows)
        self.assertTrue(all(x["reason"] == "ORPHAN_IN_B" for x in rows))
        self.assertEqual(self.get("ORG-B", reason="NOPE").status_code, 400)

    def test_sort_by_value_with_nulls_last(self):
        for key in ("a_value", "-a_value", "b_value", "-b_value"):
            with self.subTest(key=key):
                field = key.lstrip("-")
                vals = [x[field] for x in self.get("ORG-B", ordering=key).json()]
                present = [float(v) for v in vals if v is not None]
                self.assertEqual(present, sorted(present, reverse=key.startswith("-")))
                self.assertEqual(vals[len(present):], [None] * (len(vals) - len(present)))
        self.assertEqual(self.get("ORG-B", ordering="detail").status_code, 400)

    def test_summary_counts_are_tenant_scoped(self):
        body = self.client.get("/api/summary/", HTTP_X_ORG_ID="ORG-A").json()
        total = sum(r["count"] for r in body["reasons"])
        self.assertEqual(total, Discrepancy.objects.filter(org="ORG-A").count())
        self.assertEqual(body["import"]["system_a_rows"], 3)
        self.assertIsNotNone(body["last_import"])
        self.assertNotIn("stats", body)
