"""
Adversarial tenant-isolation tests (PostgreSQL). Each test tries to reach the
other tenant's data and asserts the server REJECTS it (401/403/404), or, where
the request is legitimate, that the response contains only the caller's rows.
"""
import tempfile
from pathlib import Path

from django.core import signing
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from recon.importer import import_all
from recon.models import Discrepancy, Location, SystemARecord, SystemBEntry
from recon.services import rebuild_discrepancies
from recon.tenancy import SALT

LOCATIONS = """location_id,org_id,location_name
LOC-A1,ORG-A,A one
LOC-A2,ORG-A,A two
LOC-B1,ORG-B,B one
LOC-X,ORG-A,Contested
LOC-X,ORG-B,Contested
"""
SYSTEM_A = """record_id,location_id,event_date,category_code,actor_id,base_value,adjustment,total_value,state
REC-1,LOC-A1,2026-03-01,CAT-01,U,1.00,0.00,1.00,CONFIRMED
REC-2,LOC-A2,2026-03-01,CAT-01,U,1.00,0.00,1.00,CONFIRMED
REC-3,LOC-A1,2026-03-01,CAT-01,U,5.00,0.00,5.00,CONFIRMED
REC-4,LOC-B1,2026-03-01,CAT-01,U,1.00,0.00,1.00,CONFIRMED
REC-5,LOC-B1,2026-03-01,CAT-01,U,1.00,0.00,1.00,CONFIRMED
REC-6,LOC-X,2026-03-01,CAT-01,U,1.00,0.00,1.00,CONFIRMED
"""
# REC-1 ok; REC-2 missing; REC-3 value mismatch; REC-9 orphan (ORG-A)
# REC-4 duplicate; REC-5's entry filed under ORG-A's location (cross-tenant)
SYSTEM_B = """entry_id,record_ref,location_id,recorded_on,value,label
EA1,REC-1,LOC-A1,2026-03-01,1.00,Entry for CAT-01
EA3,REC-3,LOC-A1,2026-03-01,4.00,Entry for CAT-01
EA9,REC-9,LOC-A2,2026-03-01,1.00,Entry for CAT-01
EB4,REC-4,LOC-B1,2026-03-01,1.00,Entry for CAT-01
EB4b,REC-4,LOC-B1,2026-03-01,1.00,Entry for CAT-01
EX5,REC-5,LOC-A2,2026-03-01,1.00,Entry for CAT-01
EX6,REC-6,LOC-X,2026-03-01,1.00,Entry for CAT-01
"""

OWN = {
    "ORG-A": {"locations": {"LOC-A1", "LOC-A2"}, "entries": {"EA1", "EA3", "EA9", "EX5"}, "records": {"REC-1", "REC-2", "REC-3", "REC-5", "REC-9"}},
    "ORG-B": {"locations": {"LOC-B1"}, "entries": {"EB4", "EB4b"}, "records": {"REC-4", "REC-5"}},
}


class TenantSecurityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "locations.csv").write_text(LOCATIONS)
            (d / "system_a.csv").write_text(SYSTEM_A)
            (d / "system_b.csv").write_text(SYSTEM_B)
            cls.run_stats = import_all(d).stats
        rebuild_discrepancies()

    def setUp(self):
        self.client = APIClient()

    def token(self, org):
        return self.client.post("/api/tenant-context/", {"org": org}, format="json").json()["token"]

    def call(self, path, token=None, headers=None, **params):
        h = dict(headers or {})
        if token:
            h["HTTP_AUTHORIZATION"] = f"Bearer {token}"
        return self.client.get(path, params, **h)

    # --- no / forged / tampered context -------------------------------------------------

    def test_no_context_is_rejected_not_defaulted(self):
        for path in ("/api/discrepancies/", "/api/summary/"):
            self.assertEqual(self.call(path).status_code, 401, path)

    def test_old_style_self_declared_header_is_not_a_context(self):
        # The previous design trusted this header alone. It must no longer grant anything.
        resp = self.call("/api/discrepancies/", headers={"HTTP_X_ORG_ID": "ORG-B"})
        self.assertEqual(resp.status_code, 401)

    def test_forged_token_signed_with_another_key_is_rejected(self):
        forged = signing.dumps({"org": "ORG-B"}, key="attacker-guess", salt=SALT)
        self.assertEqual(self.call("/api/discrepancies/", forged).status_code, 401)

    def test_tampered_token_is_rejected(self):
        tok = self.token("ORG-A")
        payload, sig = tok.split(":", 1)
        other = signing.dumps({"org": "ORG-B"}, salt=SALT).split(":", 1)[0]
        self.assertEqual(self.call("/api/discrepancies/", f"{other}:{sig}").status_code, 401)
        self.assertEqual(self.call("/api/discrepancies/", "not-a-token").status_code, 401)

    @override_settings(TENANT_CONTEXT_MAX_AGE=-1)
    def test_expired_context_is_rejected(self):
        self.assertEqual(self.call("/api/discrepancies/", self.token("ORG-A")).status_code, 401)

    # --- valid context, attempts to reach the other tenant --------------------------------

    def test_org_b_context_requesting_org_a_is_rejected(self):
        tok = self.token("ORG-B")
        for path in ("/api/discrepancies/", "/api/summary/"):
            for params in ({"org": "ORG-A"}, {"org_id": "ORG-A"}, {"tenant": "ORG-A"}, {"tenant_id": "ORG-A"}):
                with self.subTest(path=path, params=params):
                    self.assertEqual(self.call(path, tok, **params).status_code, 403)
            with self.subTest(path=path, header="X-Org-Id"):
                self.assertEqual(self.call(path, tok, headers={"HTTP_X_ORG_ID": "ORG-A"}).status_code, 403)
            with self.subTest(path=path, header="X-Tenant-Id"):
                self.assertEqual(self.call(path, tok, headers={"HTTP_X_TENANT_ID": "ORG-A"}).status_code, 403)

    def test_org_a_context_requesting_org_b_is_rejected(self):
        tok = self.token("ORG-A")
        self.assertEqual(self.call("/api/discrepancies/", tok, org="ORG-B").status_code, 403)
        self.assertEqual(self.call("/api/summary/", tok, headers={"HTTP_X_ORG_ID": "ORG-B"}).status_code, 403)
        # Smuggling a second value next to the legitimate one is still rejected.
        resp = self.client.get("/api/discrepancies/?org=ORG-A&org=ORG-B", HTTP_AUTHORIZATION=f"Bearer {tok}")
        self.assertEqual(resp.status_code, 403)

    def test_naming_your_own_org_is_harmless(self):
        tok = self.token("ORG-A")
        self.assertEqual(self.call("/api/discrepancies/", tok, org="ORG-A").status_code, 200)

    # --- what a legitimate context returns -------------------------------------------------

    def test_each_context_returns_only_its_own_rows(self):
        for org, own in OWN.items():
            with self.subTest(org=org):
                rows = self.call("/api/discrepancies/", self.token(org)).json()
                self.assertTrue(rows)
                self.assertLessEqual({r["location_id"] for r in rows}, own["locations"])
                self.assertLessEqual({e for r in rows for e in r["entry_ids"]}, own["entries"])
                self.assertLessEqual({r["record_id"] for r in rows}, own["records"])
                db_ids = set(Discrepancy.objects.filter(org=org).values_list("id", flat=True))
                self.assertEqual({r["id"] for r in rows}, db_ids)

    def test_disagreement_types_stay_tenant_specific(self):
        got = {org: {(r["reason"], r["record_id"]) for r in self.call("/api/discrepancies/", self.token(org)).json()}
               for org in OWN}
        self.assertEqual(got["ORG-A"], {
            ("MISSING_IN_B", "REC-2"), ("VALUE_MISMATCH", "REC-3"), ("ORPHAN_IN_B", "REC-9"),
            ("ORPHAN_IN_B", "REC-5"),  # ORG-B's record, but the entry EX5 is ORG-A's row
        })
        self.assertEqual(got["ORG-B"], {("DUPLICATE_IN_B", "REC-4"), ("MISSING_IN_B", "REC-5")})

    def test_cross_tenant_comparison_result_not_retrievable(self):
        self.assertTrue(Discrepancy.objects.filter(reason="CROSS_TENANT", org__isnull=True).exists())
        for org in OWN:
            rows = self.call("/api/discrepancies/", self.token(org)).json()
            self.assertNotIn("CROSS_TENANT", {r["reason"] for r in rows})
            self.assertEqual(self.call("/api/discrepancies/", self.token(org), reason="CROSS_TENANT").json(), [])
        # ORG-B's view of REC-5 carries no ORG-A value, entry or location.
        b_rec5 = [r for r in self.call("/api/discrepancies/", self.token("ORG-B")).json() if r["record_id"] == "REC-5"]
        self.assertEqual(b_rec5[0]["entry_ids"], [])
        self.assertIsNone(b_rec5[0]["b_value"])

    def test_summary_and_import_counts_are_tenant_specific(self):
        for org in OWN:
            body = self.call("/api/summary/", self.token(org)).json()
            self.assertEqual(body["org"], org)
            self.assertEqual(sum(r["count"] for r in body["reasons"]), Discrepancy.objects.filter(org=org).count())
            self.assertEqual(body["import"]["system_a_rows"], SystemARecord.objects.filter(org=org).count())
            self.assertEqual(body["import"]["system_b_rows"], SystemBEntry.objects.filter(org=org).count())
            self.assertNotIn("stats", body)  # global import stats never exposed

    def test_contested_location_belongs_to_no_tenant(self):
        self.assertFalse(Location.objects.filter(pk="LOC-X").exists())
        self.assertIsNone(SystemARecord.objects.get(record_id="REC-6").org)
        self.assertIsNone(SystemBEntry.objects.get(entry_id="EX6").org)
        issues = [e for i in self.run_stats["locations"]["issues"] for e in i["errors"]]
        self.assertEqual(sum("ownership ambiguous" in e for e in issues), 2)
        for org in OWN:
            rows = self.call("/api/discrepancies/", self.token(org)).json()
            self.assertNotIn("LOC-X", {r["location_id"] for r in rows})
            self.assertNotIn("REC-6", {r["record_id"] for r in rows})

    def test_no_endpoint_lists_locations_or_raw_rows(self):
        for path in ("/api/locations/", "/api/records/", "/api/entries/", "/api/discrepancies/1/"):
            self.assertEqual(self.call(path, self.token("ORG-A")).status_code, 404, path)

    # --- demo switching is an explicit, switchable server action ----------------------------

    @override_settings(ADOSX_DEMO_TENANT_SWITCHING=False)
    def test_demo_switching_can_be_disabled(self):
        self.assertEqual(self.client.post("/api/tenant-context/", {"org": "ORG-A"}, format="json").status_code, 404)
        self.assertEqual(self.client.get("/api/orgs/").status_code, 404)
        # A context issued by a trusted issuer still works; only the demo issuer is gone.
        trusted = signing.dumps({"org": "ORG-A"}, salt=SALT)
        self.assertEqual(self.call("/api/discrepancies/", trusted).status_code, 200)
