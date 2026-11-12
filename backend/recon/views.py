"""
HTTP API.

Tenant scoping: there is no authentication (out of scope), so the caller
names its tenant in the `X-Org-Id` header. In production this would come
from the authenticated session instead; nothing else would change, because
every tenant-data query goes through `TenantScopedMixin.get_org()` and
filters on it. Requests without a valid org get 400/404, never "all orgs".
Operator-only discrepancies (org=NULL) are unreachable through this API.
"""
from django.db.models import Count, F
from rest_framework import generics, serializers
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Discrepancy, ImportRun, Org, Reason, SystemARecord, SystemBEntry

ORG_HEADER = "X-Org-Id"
ORDERINGS = {
    "a_value": F("a_value").asc(nulls_last=True),
    "-a_value": F("a_value").desc(nulls_last=True),
    "b_value": F("b_value").asc(nulls_last=True),
    "-b_value": F("b_value").desc(nulls_last=True),
}


class TenantScopedMixin:
    def get_org(self):
        org_id = (self.request.headers.get(ORG_HEADER) or "").strip()
        if not org_id:
            raise ValidationError({ORG_HEADER: "This header is required."})
        try:
            return Org.objects.get(pk=org_id)
        except Org.DoesNotExist:
            raise NotFound(f"Unknown org {org_id!r}.")


class DiscrepancySerializer(serializers.ModelSerializer):
    reason_label = serializers.CharField(source="get_reason_display")

    class Meta:
        model = Discrepancy
        fields = ["id", "reason", "reason_label", "record_id", "entry_ids", "location_id",
                  "a_value", "b_value", "b_raw_value", "detail"]


class OrgListView(APIView):
    """Org ids only, so the demo UI can pick a tenant (stands in for login)."""

    def get(self, request):
        return Response([o.pk for o in Org.objects.order_by("pk")])


class DiscrepancyListView(TenantScopedMixin, generics.ListAPIView):
    """GET /api/discrepancies/?reason=VALUE_MISMATCH&ordering=-b_value  (header X-Org-Id required)"""

    serializer_class = DiscrepancySerializer

    def get_queryset(self):
        qs = Discrepancy.objects.filter(org=self.get_org())
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


class SummaryView(TenantScopedMixin, APIView):
    """Counts for the selected tenant: discrepancies per reason, and import rows with parse issues."""

    def get(self, request):
        org = self.get_org()
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
