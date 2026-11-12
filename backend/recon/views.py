"""
HTTP API. Tenant scoping is enforced by recon/tenancy.py, which DRF applies to
every view by default: `request.auth` is the Org from a server-signed tenant
context, and every tenant-data query filters on it. The client never names the
tenant for a data request; if it tries to name a different one, it gets 403.
Operator-only discrepancies (org=NULL) are unreachable through this API.
"""
from django.db.models import Count, F
from rest_framework import generics, serializers
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from django.conf import settings

from .models import Discrepancy, ImportRun, Org, Reason, SystemARecord, SystemBEntry
from .tenancy import DemoTenantSwitchingEnabled, issue_tenant_token

ORDERINGS = {
    "a_value": F("a_value").asc(nulls_last=True),
    "-a_value": F("a_value").desc(nulls_last=True),
    "b_value": F("b_value").asc(nulls_last=True),
    "-b_value": F("b_value").desc(nulls_last=True),
}


class DiscrepancySerializer(serializers.ModelSerializer):
    reason_label = serializers.CharField(source="get_reason_display")

    class Meta:
        model = Discrepancy
        fields = ["id", "reason", "reason_label", "record_id", "entry_ids", "location_id",
                  "a_value", "b_value", "b_raw_value", "detail"]


class OrgListView(APIView):
    """DEMO ONLY: org ids for the demo tenant picker. 404 when demo switching is off."""

    authentication_classes = []
    permission_classes = [DemoTenantSwitchingEnabled]

    def get(self, request):
        return Response([o.pk for o in Org.objects.order_by("pk")])


class TenantContextView(APIView):
    """DEMO ONLY stand-in for login: POST {"org": "ORG-A"} -> a signed tenant-context token.

    Switching the demo tenant is this explicit server action. Reading data then
    happens only inside the issued context. 404 when demo switching is off.
    """

    authentication_classes = []
    permission_classes = [DemoTenantSwitchingEnabled]

    def post(self, request):
        org_id = str(request.data.get("org") or "").strip()
        if not org_id:
            raise ValidationError({"org": "This field is required."})
        org = Org.objects.filter(pk=org_id).first()
        if org is None:
            raise NotFound(f"Unknown org {org_id!r}.")
        return Response({"org": org.pk, "token": issue_tenant_token(org),
                         "expires_in": settings.TENANT_CONTEXT_MAX_AGE, "mode": "demo"}, status=201)


class DiscrepancyListView(generics.ListAPIView):
    """GET /api/discrepancies/?reason=VALUE_MISMATCH&ordering=-b_value  (tenant-context token required)"""

    serializer_class = DiscrepancySerializer

    def get_queryset(self):
        qs = Discrepancy.objects.filter(org=self.request.auth)
        reason = self.request.query_params.get("reason")
        if reason:
            if reason not in Reason.values:
                raise ValidationError({"reason": f"Unknown reason {reason!r}."})
            qs = qs.filter(reason=reason)
        ordering = self.request.query_params.get("ordering")
        if ordering:
            if ordering not in ORDERINGS:
                raise ValidationError({"ordering": f"Use one of {sorted(ORDERINGS)}."})
            return qs.order_by(ORDERINGS[ordering], "record_id", "id")
        return qs.order_by("record_id", "reason", "id")


class SummaryView(APIView):
    """Counts for the selected tenant: discrepancies per reason, and import rows with parse issues."""

    def get(self, request):
        org = request.auth
        by_reason = dict(
            Discrepancy.objects.filter(org=org).values_list("reason").annotate(n=Count("id")).order_by("reason")
        )
        last_run = ImportRun.objects.order_by("-created_at").first()
        return Response({
            "org": org.pk,
            # Timestamp only: ImportRun.stats spans every tenant, so it is never exposed here.
            "last_import": last_run.created_at if last_run else None,
            "reasons": [{"code": c, "label": l, "count": by_reason.get(c, 0)} for c, l in Reason.choices],
            "import": {
                "system_a_rows": SystemARecord.objects.filter(org=org).count(),
                "system_b_rows": SystemBEntry.objects.filter(org=org).count(),
                "system_b_rows_with_issues": SystemBEntry.objects.filter(org=org).exclude(parse_errors=[]).count(),
            },
        })
