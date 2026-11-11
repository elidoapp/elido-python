"""Wire-shape types for the core Elido API resources.

Hand-rolled TypedDicts that mirror :file:`packages/api-types/src/openapi.d.ts`
for the handful of resources that this SDK exposes today: ``User``,
``Workspace``, ``Link``. Optional fields use ``NotRequired``.

These are *type-only* — at runtime the client still hands back the raw
``dict`` parsed from JSON, so adding fields server-side never breaks
callers. Picking up ``cast(User, ...)`` in your own code gives you
attribute completion in editors that understand ``TypedDict``.

If you need a richer object model (validation, conversion) wrap these
with ``pydantic.BaseModel`` in your own code — the SDK keeps the
runtime overhead at zero.
"""

from __future__ import annotations

import sys
from typing import List

if sys.version_info >= (3, 11):
    from typing import NotRequired, TypedDict
else:  # pragma: no cover — exercised on 3.9 / 3.10
    from typing_extensions import NotRequired, TypedDict


class User(TypedDict):
    """``GET /v1/me`` response."""

    id: int
    email: str
    full_name: NotRequired[str]
    timezone: NotRequired[str]
    created_at: NotRequired[str]


class Workspace(TypedDict):
    """``POST /v1/workspaces`` / ``GET /v1/workspaces/{id}``."""

    id: int
    name: str
    slug: str
    plan_tier: NotRequired[str]
    created_at: NotRequired[str]


class Link(TypedDict):
    """``POST /v1/workspaces/{ws}/links``. Subset of the openapi schema —
    new fields the server adds keep working at runtime; this just
    captures the stable spine that callers reach for in editors."""

    id: int
    workspace_id: int
    domain_id: int
    slug: str
    destination_url: str
    short_url: NotRequired[str]
    title: NotRequired[str]
    tags: NotRequired[List[str]]
    status: NotRequired[str]
    created_at: NotRequired[str]
    updated_at: NotRequired[str]


class PaginatedLinks(TypedDict):
    """``GET /v1/workspaces/{ws}/links`` response. Offset+limit, no cursor."""

    items: List[Link]
    limit: int
    offset: int


__all__ = ["Link", "PaginatedLinks", "User", "Workspace"]
