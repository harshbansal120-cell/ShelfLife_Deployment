from __future__ import annotations

import httpx
import pytest

from app import llm, search
from app.main import app

QUOTA = {"virtual_key_name": "shelflife", "is_active": True, "budgets": []}


def install(monkeypatch, handler) -> None:
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(llm, "_transport", transport)
    monkeypatch.setattr(search, "_transport", transport)


def services(
    bifrost_status: int = 200,
    tavily_status: int = 200,
    quota_status: int = 200,
    quota: dict | None = None,
    enforced: bool = True,
):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "bifrost.test":
            if request.url.path == "/health":
                return httpx.Response(bifrost_status, json={})
            if request.url.path == "/api/session/is-auth-enabled":
                return httpx.Response(200, json={"inference_auth_enforced": enforced})
            assert request.url.path == "/api/governance/virtual-keys/quota"
            assert request.headers["x-bf-vk"] == "sk-bf-test"
            return httpx.Response(quota_status, json=quota or QUOTA)
        assert request.url.path == "/usage"
        return httpx.Response(tavily_status, json={"key": {"usage": 3, "limit": 1000}})

    return handler


async def get_health() -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as client:
        return await client.get("/api/health")


async def test_health_ok_when_both_services_respond(monkeypatch):
    install(monkeypatch, services())

    response = await get_health()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["tavily"]["credits_used"] == 3
    assert body["bifrost"]["virtual_key"]["detail"] == "key 'shelflife'"
    assert body["missing_settings"] == []


@pytest.mark.parametrize(
    ("bifrost_status", "tavily_status", "failing"),
    [(500, 200, "bifrost"), (200, 401, "tavily")],
)
async def test_health_degraded_when_a_service_fails(
    monkeypatch, bifrost_status, tavily_status, failing
):
    install(monkeypatch, services(bifrost_status, tavily_status))

    response = await get_health()

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()[failing]["ok"] is False


async def test_health_reports_a_virtual_key_bifrost_does_not_know(monkeypatch):
    install(monkeypatch, services(quota_status=401))

    bifrost = (await get_health()).json()["bifrost"]

    assert bifrost["ok"] is False
    assert "BIFROST_VK" in bifrost["detail"]


async def test_health_reports_an_inactive_virtual_key(monkeypatch):
    install(monkeypatch, services(quota={**QUOTA, "is_active": False}))

    bifrost = (await get_health()).json()["bifrost"]

    assert bifrost["ok"] is False
    assert "inactive" in bifrost["detail"]


async def test_health_says_when_bifrost_needs_a_key_we_do_not_have(monkeypatch, settings):
    settings.bifrost_vk = ""
    install(monkeypatch, services(enforced=True))

    bifrost = (await get_health()).json()["bifrost"]

    assert bifrost["ok"] is False
    assert "requires a virtual key" in bifrost["detail"]


async def test_health_without_a_key_is_fine_when_bifrost_does_not_need_one(monkeypatch, settings):
    settings.bifrost_vk = ""
    install(monkeypatch, services(enforced=False))

    bifrost = (await get_health()).json()["bifrost"]

    assert bifrost["ok"] is True
    assert bifrost["virtual_key"]["configured"] is False


async def test_health_reports_unreachable_bifrost(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "bifrost.test":
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, json={"key": {}})

    install(monkeypatch, handler)

    body = (await get_health()).json()

    assert body["bifrost"]["ok"] is False
    assert "unreachable" in body["bifrost"]["detail"]
