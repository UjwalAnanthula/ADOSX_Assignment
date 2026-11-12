"""
Tenant context: which organisation a request acts for, decided server-side.

There is no authentication in this assignment (explicitly out of scope), so the
rules are:

1. A data request's tenant comes ONLY from a tenant-context token sent as
   `Authorization: Bearer <token>`. The token is signed by the server with
   SECRET_KEY (django.core.signing), so a client cannot write one for an org it
   was not issued, and editing the org inside it breaks the signature.
   Missing, malformed, tampered or expired tokens -> 401.

2. Any tenant the request names anywhere else (X-Org-Id / X-Tenant-Id headers,
   ?org= / ?org_id= / ?tenant= / ?tenant_id=) that differs from the token's org
   -> 403. A cross-tenant attempt is rejected, not silently ignored.

3. Tokens are issued by POST /api/tenant-context/. That endpoint is a DEMO
   stand-in for login: it hands out a context for any existing org, and only
   while settings.ADOSX_DEMO_TENANT_SWITCHING is on (default: on when DEBUG).
   With it off, both it and /api/orgs/ return 404 and tokens must come from a
   trusted issuer (a future login flow).

Limitation, stated plainly: while demo switching is on, anyone who can reach the
API can obtain any tenant's context. This makes "switching the demo tenant" an
explicit server action, separate from "reading data inside a context". It is NOT
production authorisation; that needs an authenticated identity bound to an org.

These classes are the REST_FRAMEWORK defaults (see settings), so a new view is
tenant-scoped unless it explicitly opts out.
"""
from django.conf import settings
from django.core import signing
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed, NotFound, PermissionDenied
from rest_framework.permissions import BasePermission

from .models import Org

SALT = "recon.tenant-context.v1"
TENANT_HEADERS = ("X-Org-Id", "X-Tenant-Id")
TENANT_QUERY_PARAMS = ("org", "org_id", "tenant", "tenant_id")


def issue_tenant_token(org):
    return signing.dumps({"org": org.pk}, salt=SALT)


class TenantTokenAuthentication(BaseAuthentication):
    """Resolves request.auth to the Org named in a valid signed token."""

    def authenticate(self, request):
        parts = get_authorization_header(request).split()
        if not parts:
            return None  # no context at all -> the permission below answers 401
        if len(parts) != 2 or parts[0].lower() != b"bearer":
            raise AuthenticationFailed("Expected 'Authorization: Bearer <tenant-context token>'.")
        try:
            payload = signing.loads(parts[1].decode("ascii", "replace"), salt=SALT,
                                    max_age=settings.TENANT_CONTEXT_MAX_AGE)
        except signing.SignatureExpired:
            raise AuthenticationFailed("Tenant context expired; request a new one.")
        except signing.BadSignature:
            raise AuthenticationFailed("Invalid tenant context.")
        org = Org.objects.filter(pk=payload.get("org")).first() if isinstance(payload, dict) else None
        if org is None:
            raise AuthenticationFailed("Tenant context refers to an unknown organisation.")
        return (None, org)

    def authenticate_header(self, request):
        return 'Bearer realm="tenant-context"'


class TenantContextRequired(BasePermission):
    """Requires a resolved tenant and rejects any request that names a different one."""

    def has_permission(self, request, view):
        org = request.auth
        if not isinstance(org, Org):
            return False  # DRF turns this into 401 because no authenticator succeeded
        named = [request.headers.get(h) for h in TENANT_HEADERS]
        named += [v for p in TENANT_QUERY_PARAMS for v in request.query_params.getlist(p)]
        foreign = sorted({n.strip() for n in named if n and n.strip()} - {org.pk})
        if foreign:
            raise PermissionDenied(
                f"This request is in tenant context {org.pk}; access to {', '.join(foreign)} is not allowed."
            )
        return True


class DemoTenantSwitchingEnabled(BasePermission):
    def has_permission(self, request, view):
        if not settings.ADOSX_DEMO_TENANT_SWITCHING:
            raise NotFound()
        return True
