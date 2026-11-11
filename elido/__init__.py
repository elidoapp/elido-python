"""Python SDK for the Elido URL shortener API.

Quick start::

    from elido import Client

    elido = Client(
        base_url="https://api.elido.app",
        token="elido_…",
    )
    me = elido.users.me()
    print(me["email"])

The client is sync-only on purpose — this is a server-side / scripting
SDK and most users want a single round-trip per call. For long-running
async workloads use ``httpx.AsyncClient`` directly with the API.
"""

from .client import Client, ElidoApiError, ElidoError
from .models import Link, PaginatedLinks, User, Workspace

__all__ = [
    "Client",
    "ElidoApiError",
    "ElidoError",
    "Link",
    "PaginatedLinks",
    "User",
    "Workspace",
]
__version__ = "0.1.0"
