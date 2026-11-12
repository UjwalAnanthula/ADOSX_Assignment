"""
Tests for the part that decides disagreements (reconcile.py) and the
parsers it depends on. Pure Python: no database needed.

Each disagreement kind has a test proving it is caught, and each "looks like
an error but isn't" case has a test proving it is NOT flagged.
"""
from datetime import date
from decimal import Decimal as D

from django.test import SimpleTestCase

from recon import reconcile as r
from recon.normalize import category_from_label, normalize_ref, parse_money
from recon.reconcile import ARecord, BEntry, reconcile


def a(record_id="REC-1", org="ORG-A", loc="LOC-101", total="100.00", **kw):
    kw.setdefault("event_date", date(2026, 3, 1))
    kw.setdefault("category_code", "CAT-01")
    return ARecord(record_id=record_id, org_id=org, location_id=loc,
                   total_value=None if total is None else D(total), **kw)


def b(entry_id="E1", ref="REC-1", org="ORG-A", loc="LOC-101", value="100.00", **kw):
    kw.setdefault("recorded_on", date(2026, 3, 1))
    kw.setdefault("label", "Entry for CAT-01")
    return BEntry(entry_id=entry_id, ref=ref, org_id=org, location_id=loc,
                  value=None if value is None else D(value), raw_value=kw.pop("raw_value", value or ""), **kw)


def reasons(findings):
    return sorted((f.reason, f.record_id) for f in findings)


class CleanMatchTests(SimpleTestCase):
    def test_identical_rows_produce_no_findings(self):
        self.assertEqual(reconcile([a()], [b()]), [])


class RequiredDisagreementTests(SimpleTestCase):
    def test_record_in_a_with_no_entry_in_b(self):
        self.assertEqual(reasons(reconcile([a()], [])), [(r.MISSING_IN_B, "REC-1")])

    def test_b_entry_pointing_at_record_that_does_not_exist(self):
        found = reconcile([a()], [b(), b(entry_id="E9", ref="REC-999")])
        self.assertEqual(reasons(found), [(r.ORPHAN_IN_B, "REC-999")])
        self.assertEqual(found[0].entry_ids, ["E9"])

    def test_unrecognisable_reference_is_an_orphan_not_a_crash(self):
        found = reconcile([a()], [b(), b(entry_id="E9", ref=None, raw_ref="INV-??")])
        self.assertEqual([f.reason for f in found], [r.ORPHAN_IN_B])
        self.assertIn("INV-??", found[0].detail)

    def test_same_record_entered_into_b_twice(self):
        found = reconcile([a()], [b(entry_id="E1"), b(entry_id="E2")])
        self.assertEqual(reasons(found), [(r.DUPLICATE_IN_B, "REC-1")])
        self.assertEqual(found[0].b_value, D("200.00"))
        self.assertEqual(found[0].entry_ids, ["E1", "E2"])

    def test_different_values_for_same_record(self):
        found = reconcile([a(total="100.00")], [b(value="100.01")])
        self.assertEqual(reasons(found), [(r.VALUE_MISMATCH, "REC-1")])
        self.assertEqual((found[0].a_value, found[0].b_value), (D("100.00"), D("100.01")))

    def test_value_mismatch_explains_missing_adjustment(self):
        found = reconcile([a(total="128.00", base_value=D("100.00"))], [b(value="100.00")])
        self.assertIn("base_value", found[0].detail)


class NonErrorTests(SimpleTestCase):
    """Things that look wrong but are not disagreements."""

    def test_split_entry_that_sums_to_total_is_not_a_duplicate_or_mismatch(self):
        entries = [b(entry_id="E1", value="40.00"), b(entry_id="E2", value="60.00", label="Entry part 2 of 2")]
        self.assertEqual(reconcile([a(total="100.00")], entries), [])

    def test_split_entry_that_does_not_sum_is_flagged(self):
        entries = [b(entry_id="E1", value="40.00"), b(entry_id="E2", value="59.00")]
        self.assertEqual([f.reason for f in reconcile([a()], entries)], [r.DUPLICATE_IN_B])

    def test_messy_references_still_match(self):
        for raw in ["REC-1034", "rec1034", " REC - 1034 ", "1034", "Rec-1034"]:
            with self.subTest(raw=raw):
                self.assertEqual(normalize_ref(raw), "REC-1034")

    def test_label_without_category_makes_no_category_claim(self):
        self.assertIsNone(category_from_label("Entry part 2 of 2"))
        self.assertEqual(reconcile([a()], [b(label="Entry part 2 of 2")]), [])


class DirtyValueTests(SimpleTestCase):
    def test_blank_b_value_is_unparseable_not_zero(self):
        found = reconcile([a()], [b(value=None, raw_value="")])
        self.assertEqual([f.reason for f in found], [r.UNPARSEABLE_VALUE])
        self.assertIsNone(found[0].b_value)

    def test_unparseable_a_value_is_flagged(self):
        found = reconcile([a(total=None, raw_total_value="N/A")], [b()])
        self.assertEqual([f.reason for f in found], [r.UNPARSEABLE_VALUE])
        self.assertIn("N/A", found[0].detail)

    def test_money_parsing(self):
        self.assertEqual(parse_money("1,25,400.00"), (D("125400.00"), None))  # Indian grouping
        self.assertEqual(parse_money("125,400.00"), (D("125400.00"), None))
        self.assertEqual(parse_money(" 88969.92 "), (D("88969.92"), None))
        for bad in ["", "   ", None, "abc", "1.234,56", "12.3.4", "$100", "1,2", "12,34.00", ",100"]:
            with self.subTest(bad=bad):
                self.assertIsNone(parse_money(bad)[0])
                self.assertIsNotNone(parse_money(bad)[1])

    def test_malformed_references_are_not_guessed(self):
        for raw in ["", "REC-", "INV-1034", "REC-10A4", "abc", None]:
            with self.subTest(raw=raw):
                self.assertIsNone(normalize_ref(raw))


class OtherFieldTests(SimpleTestCase):
    def test_date_mismatch(self):
        found = reconcile([a()], [b(recorded_on=date(2026, 3, 2))])
        self.assertEqual([f.reason for f in found], [r.DATE_MISMATCH])

    def test_location_mismatch_within_same_org(self):
        found = reconcile([a(loc="LOC-101")], [b(loc="LOC-102")])
        self.assertEqual([f.reason for f in found], [r.LOCATION_MISMATCH])

    def test_category_mismatch_from_label(self):
        found = reconcile([a()], [b(label="Entry for CAT-07")])
        self.assertEqual([f.reason for f in found], [r.CATEGORY_MISMATCH])

    def test_voided_in_a_but_live_in_b(self):
        found = reconcile([a(state="VOIDED")], [b()])
        self.assertEqual([f.reason for f in found], [r.VOIDED_IN_A])

    def test_duplicate_record_id_in_a(self):
        found = reconcile([a(), a()], [b()])
        self.assertEqual([f.reason for f in found], [r.DUPLICATE_IN_A])


class TenantBoundaryTests(SimpleTestCase):
    def setUp(self):
        # REC-7 belongs to ORG-A, but System B filed its entry under ORG-B's location.
        self.findings = reconcile(
            [a(record_id="REC-7", org="ORG-A", loc="LOC-101", total="500.00")],
            [b(entry_id="E7", ref="REC-7", org="ORG-B", loc="LOC-201", value="500.00")],
        )

    def test_records_never_match_across_orgs(self):
        by_org = {(f.org_id, f.reason) for f in self.findings}
        self.assertIn(("ORG-A", r.MISSING_IN_B), by_org)
        self.assertIn(("ORG-B", r.ORPHAN_IN_B), by_org)

    def test_tenant_findings_contain_only_that_tenants_data(self):
        for f in self.findings:
            if f.org_id == "ORG-A":
                self.assertEqual(f.entry_ids, [])           # no ORG-B entry ids
                self.assertNotEqual(f.location_id, "LOC-201")
                self.assertIsNone(f.b_value)               # no ORG-B values
            if f.org_id == "ORG-B":
                self.assertIsNone(f.a_value)               # no ORG-A values
                self.assertNotIn("ORG-A", f.detail)
                self.assertNotEqual(f.location_id, "LOC-101")

    def test_cross_tenant_reference_is_operator_only(self):
        cross = [f for f in self.findings if f.reason == r.CROSS_TENANT]
        self.assertEqual(len(cross), 1)
        self.assertIsNone(cross[0].org_id)

    def test_unknown_location_has_no_tenant(self):
        found = reconcile([a(org=None, loc="LOC-999")], [])
        self.assertTrue(found)
        self.assertTrue(all(f.org_id is None for f in found))
        self.assertIn(r.UNKNOWN_LOCATION, [f.reason for f in found])
