"""
Regression test against the real assignment files. Skipped when they are not
present in data/ (they are not committed; see data/README.md).

The expected set was checked by reading the CSVs, not copied from program
output. If a change to the rules alters this set, the test should fail loudly.
"""
import unittest

from django.conf import settings
from django.test import TestCase

from recon.importer import import_all
from recon.models import Discrepancy
from recon.services import rebuild_discrepancies

HAVE_DATA = all((settings.DATA_DIR / f"{n}.csv").exists() for n in ("locations", "system_a", "system_b"))

EXPECTED = {
    ("ORG-A", "MISSING_IN_B", "REC-1015"),
    ("ORG-A", "MISSING_IN_B", "REC-1077"),     # its B entry sits under ORG-B
    ("ORG-A", "ORPHAN_IN_B", "REC-1999"),
    ("ORG-A", "DUPLICATE_IN_B", "REC-1042"),
    ("ORG-A", "VALUE_MISMATCH", "REC-1027"),   # B = base_value
    ("ORG-A", "VALUE_MISMATCH", "REC-1064"),   # "1,25,400.00" vs 183244.16
    ("ORG-A", "VALUE_MISMATCH", "REC-1088"),   # B = base_value
    ("ORG-B", "MISSING_IN_B", "REC-1061"),
    ("ORG-B", "ORPHAN_IN_B", "REC-1077"),      # entry under LOC-201, record is ORG-A's
    ("ORG-B", "VALUE_MISMATCH", "REC-1003"),   # B = base_value
    ("ORG-B", "UNPARSEABLE_VALUE", "REC-1050"),
    ("ORG-B", "DATE_MISMATCH", "REC-1009"),
    ("ORG-B", "VOIDED_IN_A", "REC-1019"),
    (None, "CROSS_TENANT", "REC-1077"),
}


@unittest.skipUnless(HAVE_DATA, "assignment CSVs not present in data/")
class AssignmentDatasetTests(TestCase):
    def setUp(self):
        self.run = import_all(settings.DATA_DIR)
        rebuild_discrepancies()

    def test_every_row_imported(self):
        self.assertEqual({k: (v["rows_read"], v["rows_stored"]) for k, v in self.run.stats.items()},
                         {"locations": (5, 5), "system_a": (120, 120), "system_b": (121, 121)})

    def test_exact_discrepancy_set(self):
        got = set(Discrepancy.objects.values_list("org", "reason", "record_id"))
        self.assertEqual(got, EXPECTED)

    def test_split_entry_rec_1055_is_not_flagged(self):
        self.assertFalse(Discrepancy.objects.filter(record_id="REC-1055").exists())

    def test_messy_refs_matched(self):
        for rec in ("REC-1034", "REC-1070", "REC-1112"):
            self.assertFalse(Discrepancy.objects.filter(record_id=rec).exists(), rec)
