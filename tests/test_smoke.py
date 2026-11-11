"""Smoke tests for the Elido Python SDK.

Covers wire-shape happy paths against a mock httpx server. Real API
integration runs in the server-side smoke suite.
"""

from __future__ import annotations

import httpx
import pytest

from elido import Client, ElidoApiError


def make_client(transport: httpx.MockTransport) -> Client:
    return Client(
        base_url="https://api.test",
        token="elido_test",
        http_client=httpx.Client(transport=transport),
    )


def test_workspaces_list_passes_bearer_and_returns_items() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization", "")
        return httpx.Response(200, json={"items": [{"id": 1, "name": "Acme"}]})

    transport = httpx.MockTransport(handler)
    elido = make_client(transport)
    out = elido.workspaces.list()
    assert out == {"items": [{"id": 1, "name": "Acme"}]}
    assert captured["url"] == "https://api.test/v1/workspaces"
    assert captured["auth"] == "Bearer elido_test"


def test_links_list_drops_none_params() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["query"] = str(request.url.params)
        return httpx.Response(200, json={"items": [], "limit": 20, "offset": 0})

    transport = httpx.MockTransport(handler)
    elido = make_client(transport)
    elido.links.list(7, limit=20)
    assert "limit=20" in captured["query"]
    assert "offset" not in captured["query"]  # None was filtered


def test_links_list_serialises_tags_and_folder() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["query"] = str(request.url.params)
        return httpx.Response(200, json={"items": []})

    transport = httpx.MockTransport(handler)
    elido = make_client(transport)
    elido.links.list(7, tags=["a", "b"], folder=42)
    assert "tags=a%2Cb" in captured["query"]
    assert "folder=42" in captured["query"]


def test_api_error_propagates_status_and_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not found"})

    transport = httpx.MockTransport(handler)
    elido = make_client(transport)
    with pytest.raises(ElidoApiError) as exc:
        elido.workspaces.get(99)
    assert exc.value.status == 404
    assert exc.value.message == "not found"


def test_204_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    transport = httpx.MockTransport(handler)
    elido = make_client(transport)
    assert elido.links.delete(7, 99) is None


def test_dev_user_id_path() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["dev"] = request.headers.get("x-dev-user-id", "")
        return httpx.Response(200, json={"items": []})

    transport = httpx.MockTransport(handler)
    elido = Client(
        base_url="https://api.test",
        dev_user_id=1,
        http_client=httpx.Client(transport=transport),
    )
    elido.workspaces.list()
    assert captured["dev"] == "1"


def test_users_me_returns_self() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={"id": 7, "email": "alice@example.com", "full_name": "Alice"},
        )

    transport = httpx.MockTransport(handler)
    elido = make_client(transport)
    me = elido.users.me()
    assert me["id"] == 7
    assert me["email"] == "alice@example.com"
    assert captured["url"] == "https://api.test/v1/me"
