"""Hand-rolled Elido API client.

The mirror of @elido/sdk (TypeScript). Resources are exposed as
attribute namespaces (``client.workspaces.list()``,
``client.links.create(workspace_id, …)``) so the call sites read
roughly the same in either language.

Auth picks up the first non-None of:
  * ``token`` — bearer API key (``elido_…`` from ``/dashboard/api-keys``)
  * ``cookie`` — raw ``Cookie`` header (session passthrough)
  * ``dev_user_id`` — local-dev only; sets ``X-Dev-User-ID``

Network errors and >=400 responses raise :class:`ElidoApiError`. The
caller can catch + retry; the SDK never retries automatically because
PATCH/POST aren't idempotent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, cast
import json
import urllib.parse

import httpx

from .models import Link, PaginatedLinks, User, Workspace


class ElidoError(Exception):
    """Base class for SDK errors."""


@dataclass
class ElidoApiError(ElidoError):
    """API returned a non-2xx response."""

    status: int
    body: Any
    message: str

    def __str__(self) -> str:  # pragma: no cover
        return f"Elido API {self.status}: {self.message}"


_DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=3.0)


class Client:
    """Sync HTTP client for the Elido API.

    Parameters
    ----------
    base_url:
        Root URL of the API (e.g. ``"https://api.elido.app"`` or
        ``"http://localhost:8085"``).
    token:
        Bearer API key. Mutually exclusive with ``cookie`` /
        ``dev_user_id`` — first non-None wins.
    cookie:
        Raw ``Cookie`` header to forward (server-to-server pattern
        where the browser session is reused).
    dev_user_id:
        Sends ``X-Dev-User-ID`` for local-dev bypass. Production rejects
        this header.
    analytics_base_url / billing_base_url / webhook_base_url /
    domain_base_url / qr_base_url / metadata_base_url:
        Override the URL the SDK uses for the matching service. They
        default to ``base_url`` so a single hostname / Caddy routing
        works out of the box.
    timeout:
        Forwarded to ``httpx``. Defaults to 10s.
    """

    def __init__(
        self,
        *,
        base_url: str,
        token: str | None = None,
        cookie: str | None = None,
        dev_user_id: str | int | None = None,
        analytics_base_url: str | None = None,
        billing_base_url: str | None = None,
        webhook_base_url: str | None = None,
        domain_base_url: str | None = None,
        qr_base_url: str | None = None,
        metadata_base_url: str | None = None,
        timeout: httpx.Timeout | float | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._token = token
        self._cookie = cookie
        self._dev_user_id = dev_user_id
        self._analytics = (analytics_base_url or base_url).rstrip("/")
        self._billing = (billing_base_url or base_url).rstrip("/")
        self._webhook = (webhook_base_url or base_url).rstrip("/")
        self._domain = (domain_base_url or base_url).rstrip("/")
        self._qr = (qr_base_url or base_url).rstrip("/")
        self._metadata = (metadata_base_url or base_url).rstrip("/")
        self._http = http_client or httpx.Client(
            timeout=timeout or _DEFAULT_TIMEOUT,
        )
        self._owns_http = http_client is None

        # Resource namespaces.
        self.users = _Users(self)
        self.workspaces = _Workspaces(self)
        self.links = _Links(self)
        self.folders = _Folders(self)
        self.api_keys = _APIKeys(self)
        self.invitations = _Invitations(self)
        self.analytics = _Analytics(self)
        self.billing = _Billing(self)
        self.pixels = _Pixels(self)
        self.compliance = _Compliance(self)

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> "Client":  # pragma: no cover
        return self

    def __exit__(self, *_exc: Any) -> None:  # pragma: no cover
        self.close()

    def _headers(self, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        h: dict[str, str] = {"Accept": "application/json"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        elif self._cookie:
            h["Cookie"] = self._cookie
        elif self._dev_user_id is not None:
            h["X-Dev-User-ID"] = str(self._dev_user_id)
        if extra:
            h.update(extra)
        return h

    def _request(
        self,
        base: str,
        method: str,
        path: str,
        *,
        body: Any = None,
        params: Mapping[str, Any] | None = None,
        return_text: bool = False,
    ) -> Any:
        url = f"{base}{path}"
        headers = self._headers(
            {"Content-Type": "application/json"} if body is not None else None
        )
        try:
            resp = self._http.request(
                method,
                url,
                headers=headers,
                params=_params(params),
                json=body if body is not None else None,
            )
        except httpx.HTTPError as exc:
            raise ElidoError(f"{method} {url}: {exc}") from exc
        if resp.status_code == 204:
            return None
        if not resp.is_success:
            try:
                payload = resp.json()
                message = (
                    payload.get("error")
                    if isinstance(payload, dict) and isinstance(payload.get("error"), str)
                    else f"{method} {path} → {resp.status_code}"
                )
            except json.JSONDecodeError:
                payload = resp.text
                message = f"{method} {path} → {resp.status_code}"
            raise ElidoApiError(status=resp.status_code, body=payload, message=message)
        if return_text:
            return resp.text
        if not resp.content:
            return None
        ct = resp.headers.get("content-type", "")
        if "application/json" in ct:
            return resp.json()
        return resp.text


def _params(p: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Drop None values so httpx doesn't emit ``foo=None`` in the URL."""
    if not p:
        return None
    return {k: v for k, v in p.items() if v is not None}


# === Resource classes ===
#
# Each namespace takes the parent Client by reference so we don't copy
# auth state. Methods stay thin — argument shaping + path templating —
# and never inspect the response further than passing it back.


class _Users:
    """``/v1/me`` and friends. Resolves the authenticated principal —
    bearer token, session cookie, or X-Dev-User-ID."""

    def __init__(self, c: Client) -> None:
        self._c = c

    def me(self) -> User:
        """Returns the authenticated user. Raises ``ElidoApiError(401)``
        if no auth credential is set / the token is rejected."""
        return cast(
            User,
            self._c._request(self._c._base, "GET", "/v1/me"),
        )

    def update_my_timezone(self, timezone: str) -> dict[str, Any]:
        """``PATCH /v1/me/timezone``. ``timezone`` is an IANA zone name
        (``"Europe/Berlin"``); the server validates via
        ``time.LoadLocation``."""
        return self._c._request(
            self._c._base, "PATCH", "/v1/me/timezone",
            body={"timezone": timezone},
        )


class _Workspaces:
    def __init__(self, c: Client) -> None:
        self._c = c

    def list(self) -> dict[str, Any]:
        return self._c._request(self._c._base, "GET", "/v1/workspaces")

    def create(self, *, name: str, slug: str) -> Workspace:
        return cast(
            Workspace,
            self._c._request(
                self._c._base, "POST", "/v1/workspaces",
                body={"name": name, "slug": slug},
            ),
        )

    def get(self, workspace_id: int) -> Workspace:
        return cast(
            Workspace,
            self._c._request(
                self._c._base, "GET", f"/v1/workspaces/{workspace_id}",
            ),
        )

    def update(self, workspace_id: int, **patch: Any) -> dict[str, Any]:
        return self._c._request(
            self._c._base, "PATCH", f"/v1/workspaces/{workspace_id}",
            body=patch,
        )

    def members(self, workspace_id: int) -> dict[str, Any]:
        return self._c._request(
            self._c._base, "GET", f"/v1/workspaces/{workspace_id}/members",
        )


class _Links:
    def __init__(self, c: Client) -> None:
        self._c = c

    def list(
        self,
        workspace_id: int,
        *,
        limit: int | None = None,
        offset: int | None = None,
        tags: Iterable[str] | None = None,
        q: str | None = None,
        folder: int | str | None = None,
    ) -> PaginatedLinks:
        params: dict[str, Any] = {"limit": limit, "offset": offset, "q": q}
        if tags:
            params["tags"] = ",".join(tags)
        if folder is not None:
            params["folder"] = folder
        return cast(
            PaginatedLinks,
            self._c._request(
                self._c._base, "GET", f"/v1/workspaces/{workspace_id}/links",
                params=params,
            ),
        )

    def create(self, workspace_id: int, **body: Any) -> Link:
        return cast(
            Link,
            self._c._request(
                self._c._base, "POST", f"/v1/workspaces/{workspace_id}/links",
                body=body,
            ),
        )

    def update(self, workspace_id: int, link_id: int, **patch: Any) -> dict[str, Any]:
        return self._c._request(
            self._c._base, "PATCH",
            f"/v1/workspaces/{workspace_id}/links/{link_id}",
            body=patch,
        )

    def delete(self, workspace_id: int, link_id: int) -> None:
        return self._c._request(
            self._c._base, "DELETE",
            f"/v1/workspaces/{workspace_id}/links/{link_id}",
        )

    def bulk_create(self, workspace_id: int, *, domain_id: int, links: list[dict[str, Any]]) -> dict[str, Any]:
        return self._c._request(
            self._c._base, "POST",
            f"/v1/workspaces/{workspace_id}/links/bulk",
            body={"domain_id": domain_id, "links": links},
        )

    def bulk_mutate(self, workspace_id: int, **body: Any) -> dict[str, Any]:
        return self._c._request(
            self._c._base, "POST",
            f"/v1/workspaces/{workspace_id}/links/bulk-mutate",
            body=body,
        )


class _Folders:
    def __init__(self, c: Client) -> None:
        self._c = c

    def list(self, workspace_id: int) -> dict[str, Any]:
        return self._c._request(
            self._c._base, "GET", f"/v1/workspaces/{workspace_id}/folders",
        )

    def create(self, workspace_id: int, *, name: str, color: str | None = None) -> dict[str, Any]:
        return self._c._request(
            self._c._base, "POST", f"/v1/workspaces/{workspace_id}/folders",
            body={"name": name, "color": color} if color else {"name": name},
        )

    def update(self, workspace_id: int, folder_id: int, **patch: Any) -> dict[str, Any]:
        return self._c._request(
            self._c._base, "PATCH",
            f"/v1/workspaces/{workspace_id}/folders/{folder_id}",
            body=patch,
        )

    def delete(self, workspace_id: int, folder_id: int) -> None:
        return self._c._request(
            self._c._base, "DELETE",
            f"/v1/workspaces/{workspace_id}/folders/{folder_id}",
        )


class _APIKeys:
    def __init__(self, c: Client) -> None:
        self._c = c

    def list(self, workspace_id: int) -> dict[str, Any]:
        return self._c._request(
            self._c._base, "GET", f"/v1/workspaces/{workspace_id}/api-keys",
        )

    def create(self, workspace_id: int, *, name: str, role: str = "editor") -> dict[str, Any]:
        return self._c._request(
            self._c._base, "POST", f"/v1/workspaces/{workspace_id}/api-keys",
            body={"name": name, "role": role},
        )

    def revoke(self, workspace_id: int, key_id: int) -> None:
        return self._c._request(
            self._c._base, "DELETE",
            f"/v1/workspaces/{workspace_id}/api-keys/{key_id}",
        )


class _Invitations:
    def __init__(self, c: Client) -> None:
        self._c = c

    def list(self, workspace_id: int) -> dict[str, Any]:
        return self._c._request(
            self._c._base, "GET", f"/v1/workspaces/{workspace_id}/invitations",
        )

    def create(self, workspace_id: int, *, email: str, role: str) -> dict[str, Any]:
        return self._c._request(
            self._c._base, "POST", f"/v1/workspaces/{workspace_id}/invitations",
            body={"email": email, "role": role},
        )

    def revoke(self, workspace_id: int, invitation_id: int) -> None:
        return self._c._request(
            self._c._base, "DELETE",
            f"/v1/workspaces/{workspace_id}/invitations/{invitation_id}",
        )


class _Analytics:
    def __init__(self, c: Client) -> None:
        self._c = c

    def timeseries(
        self,
        workspace_id: int,
        *,
        from_: str,
        to: str,
        interval: str | None = None,
        link_id: int | None = None,
    ) -> dict[str, Any]:
        return self._c._request(
            self._c._analytics, "GET",
            f"/v1/analytics/workspaces/{workspace_id}/timeseries",
            params={"from": from_, "to": to, "interval": interval, "link_id": link_id},
        )

    def top_links(
        self,
        workspace_id: int,
        *,
        from_: str,
        to: str,
        limit: int | None = None,
    ) -> dict[str, Any]:
        return self._c._request(
            self._c._analytics, "GET",
            f"/v1/analytics/workspaces/{workspace_id}/links/top",
            params={"from": from_, "to": to, "limit": limit},
        )

    def ltv(
        self,
        workspace_id: int,
        *,
        from_: str,
        to: str,
        currency: str | None = None,
        link_id: int | None = None,
    ) -> dict[str, Any]:
        """Lifetime-value report — one row per acquisition cohort.

        Joins ClickHouse engagement (visitors, clicks) with attributed
        revenue from Stripe / Shopify conversions in Postgres. The
        ``currency`` filter scopes revenue to one ISO currency (default
        ``USD``); cohorts with no conversions in that currency report
        ``revenue_cents == 0``.
        """
        return self._c._request(
            self._c._analytics, "GET",
            f"/v1/analytics/workspaces/{workspace_id}/ltv",
            params={
                "from": from_, "to": to,
                "currency": currency, "link_id": link_id,
            },
        )


class _Billing:
    def __init__(self, c: Client) -> None:
        self._c = c

    def plans(self) -> dict[str, Any]:
        return self._c._request(self._c._billing, "GET", "/v1/billing/plans")

    def subscription(self, workspace_id: int) -> dict[str, Any]:
        return self._c._request(
            self._c._billing, "GET",
            f"/v1/billing/workspaces/{workspace_id}/subscription",
        )

    def checkout(self, workspace_id: int, plan_id: int) -> dict[str, Any]:
        return self._c._request(
            self._c._billing, "POST",
            f"/v1/billing/workspaces/{workspace_id}/checkout",
            body={"plan_id": plan_id},
        )

    def cancel(self, workspace_id: int) -> None:
        return self._c._request(
            self._c._billing, "POST",
            f"/v1/billing/workspaces/{workspace_id}/subscription/cancel",
        )


class _Compliance:
    def __init__(self, c: Client) -> None:
        self._c = c

    def get(self, workspace_id: int) -> dict[str, Any]:
        return self._c._request(
            self._c._base, "GET",
            f"/v1/workspaces/{workspace_id}/compliance",
        )

    def update(self, workspace_id: int, **body: Any) -> dict[str, Any]:
        return self._c._request(
            self._c._base, "PUT",
            f"/v1/workspaces/{workspace_id}/compliance",
            body=body,
        )

    def evidence(self, workspace_id: int) -> dict[str, Any]:
        """SOC 2 / HIPAA evidence snapshot — JSON view of posture +
        access controls + audit volume + SSO/SCIM bindings.
        """
        return self._c._request(
            self._c._base, "GET",
            f"/v1/workspaces/{workspace_id}/compliance/evidence",
        )

    def evidence_bundle_url(self, workspace_id: int) -> str:
        """URL of the streaming ZIP bundle. Caller fetches with its own
        auth headers so the response can stream straight to disk.
        """
        return f"{self._c._base}/v1/workspaces/{workspace_id}/compliance/evidence.zip"


class _Pixels:
    def __init__(self, c: Client) -> None:
        self._c = c

    def get(self, workspace_id: int) -> dict[str, Any]:
        return self._c._request(
            self._c._base, "GET", f"/v1/workspaces/{workspace_id}/pixels",
        )

    def upsert(self, workspace_id: int, **body: Any) -> dict[str, Any]:
        return self._c._request(
            self._c._base, "PUT", f"/v1/workspaces/{workspace_id}/pixels",
            body=body,
        )

    def delete(self, workspace_id: int) -> None:
        return self._c._request(
            self._c._base, "DELETE", f"/v1/workspaces/{workspace_id}/pixels",
        )


# Avoids "imported but unused" on urllib.parse — kept as a future hook
# for path-segment escaping if/when we surface user-supplied slugs in
# URLs (today they're all integer IDs).
_unused = urllib.parse.quote
