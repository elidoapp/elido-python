# elido-sdk — Python SDK

Sync HTTP client for the [Elido](https://elido.app) URL-shortener API.

```python
from elido import Client

elido = Client(
    base_url="https://api.elido.app",
    token="elido_...",
)

# Who am I?
me = elido.users.me()
print(me["email"])

# Create a link
link = elido.links.create(
    workspace_id=42,
    domain_id=1,
    destination_url="https://example.com/landing",
    tags=["spring-2026"],
)
print(link["slug"])

# Last-30-day clicks per link
top = elido.analytics.top_links(
    workspace_id=42,
    from_="2026-04-01",
    to="2026-05-01",
    limit=20,
)
for row in top["items"]:
    print(row["link_id"], row["count"])
```

## Types

The core resource shapes (`User`, `Workspace`, `Link`, `PaginatedLinks`) are exposed as `TypedDict`s for editor completion. They're type-only — the runtime client still hands back raw dicts, so unknown fields the server adds keep working without a SDK release:

```python
from elido import Client, Link

elido = Client(base_url="https://api.elido.app", token="elido_...")
link: Link = elido.links.create(42, domain_id=1, destination_url="https://example.com/x")
```

## Auth

In order of precedence:

| Constructor arg                   | Header sent               | Use case            |
| --------------------------------- | ------------------------- | ------------------- |
| `token="elido_..."`               | `Authorization: Bearer …` | Production scripts  |
| `cookie="ory_kratos_session=..."` | `Cookie: …`               | Server-side proxies |

API keys start with the `elido_` prefix and are created in the Elido dashboard under API keys. Plain `elido_…` strings are
shown once on creation and stored hashed; rotate with `api_keys.create`

- `api_keys.revoke(old_id)`.

## Multi-host setups

If you front Elido with separate hostnames per service, pass the URLs
explicitly:

```python
elido = Client(
    base_url="https://api.elido.app",
    analytics_base_url="https://analytics.elido.app",
    billing_base_url="https://billing.elido.app",
    token="elido_...",
)
```

The default keeps everything on `base_url`.

## Errors

`elido.ElidoApiError` carries `status`, `body`, `message`. Catch it for
4xx/5xx responses; transport-level errors raise `ElidoError`.

## Install

```bash
pip install elido-sdk
```

The distribution is called `elido-sdk` on PyPI; the import name is `elido`
(`from elido import Client`). Requires Python 3.9+.

## Versioning

This SDK is hand-written against Elido's public OpenAPI spec (<https://elido.app/openapi.json>).
Add or rename a field server-side, the SDK keeps working as long as
the wire JSON stays. Breaking changes bump the SDK minor.

## Links

- Documentation: <https://elido.app/docs>
- Issues: <https://github.com/elidoapp/elido-python/issues>
- Changelog: [CHANGELOG.md](./CHANGELOG.md)

## License

[MIT](./LICENSE) (c) Elido. The Elido service itself is a separate, hosted
product; this repository contains only the client library.
