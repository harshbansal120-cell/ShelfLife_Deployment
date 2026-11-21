"""Workspace features through the API, against the simulator. All data is invented."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app import alerts, config, demo, links, llm, main, search
from app.demo.simulator import CLOUD_ANSWER, CLOUD_QUESTION, FACTS_ANSWER, VAULT_ANSWERS, Simulator
from app.jobs import CheckStore


@pytest.fixture
def simulator(monkeypatch):
    fake = Simulator(latency=(0, 0))
    transport = httpx.MockTransport(fake)
    monkeypatch.setattr(llm, "_transport", transport)
    monkeypatch.setattr(search, "_transport", transport)
    monkeypatch.setattr(links, "_transport", transport)
    monkeypatch.setattr(links, "_public_only", False)
    return fake


@pytest.fixture
async def client(simulator, monkeypatch):
    monkeypatch.setattr(main, "checks", CheckStore())
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test", timeout=30) as api:
        yield api


async def verify(client, answer, **extra):
    response = await client.post("/api/verify", json={"answer": answer, **extra})
    assert response.status_code == 200, response.text
    return response.json()


# --- verify, guard and passports -------------------------------------------------


async def test_verify_says_whether_to_show_the_answer(client):
    cloud = await verify(client, CLOUD_ANSWER, question=CLOUD_QUESTION)
    facts = await verify(client, FACTS_ANSWER)

    assert cloud["guard"]["action"] == "withhold"
    assert facts["guard"]["action"] == "show_with_warning"


async def test_claim_registry_keeps_a_passport_per_claim(client):
    await verify(client, FACTS_ANSWER)
    await verify(client, FACTS_ANSWER)

    claims = (await client.get("/api/claims")).json()["claims"]
    price = next(c for c in claims if c["text"].startswith("Acme Cloud costs"))
    passport = (await client.get(f"/api/claims/{price['id']}")).json()

    assert price["checks"] == 2 and price["status"] == "stale"
    assert passport["id"].startswith("CLM-") and len(passport["history"]) == 2
    assert "acme.example" in passport["sources"]
    stale_only = (await client.get("/api/claims?status=stale")).json()["claims"]
    assert all(c["status"] == "stale" for c in stale_only)
    assert (await client.get("/api/claims/CLM-NOPE00")).status_code == 404


# --- compare -----------------------------------------------------------------------


async def test_compare_finds_which_assistant_is_out_of_date(client):
    response = await client.post("/api/compare", json={"answers": VAULT_ANSWERS})

    body = response.json()
    assert response.status_code == 200, response.text
    assert body["conflicts"] == 2
    users = next(c for c in body["clusters"] if "users" in c["topic"])
    verdicts = {row["app"]: row["verdict"] for row in users["entries"]}
    assert verdicts == {"Sales assistant": "stale", "Support assistant": "stale", "Docs assistant": "fresh"}
    assert users["current_value"] == "8,000 users"
    docs = next(app for app in body["apps"] if app["app"] == "Docs assistant")
    assert docs["stale"] == 0 and docs["fresh"] == 2
    assert (await client.get("/api/comparisons")).json()["comparisons"][0]["id"] == body["id"]


async def test_compare_needs_two_answers(client):
    response = await client.post("/api/compare", json={"answers": VAULT_ANSWERS[:1]})
    assert response.status_code == 422


# --- regression tests ------------------------------------------------------------


async def test_regression_test_fails_when_the_answer_goes_stale(client):
    created = (await client.post("/api/tests", json={
        "name": "Cloud advice", "question": CLOUD_QUESTION, "must_include": ["India", "Kubernetes"],
    })).json()

    run = (await client.post(f"/api/tests/{created['id']}/run")).json()

    assert run["passed"] is False
    assert any(problem.startswith("Stale:") for problem in run["problems"])
    assert 'Missing: "Kubernetes"' in run["problems"]
    tests = (await client.get("/api/tests")).json()["tests"]
    assert tests[0]["last_run"]["id"] == run["id"] and tests[0]["recent"] == [False]
    assert (await client.get(f"/api/checks/{run['check_id']}")).status_code == 200


async def test_regression_tests_can_be_deleted(client):
    created = (await client.post("/api/tests", json={"name": "x", "question": "Q?"})).json()

    await client.delete(f"/api/tests/{created['id']}")

    assert (await client.get("/api/tests")).json()["tests"] == []
    assert (await client.post(f"/api/tests/{created['id']}/run")).status_code == 404


# --- context profiles and drift ------------------------------------------------------


async def test_profile_context_is_used_and_changes_are_tracked(client):
    profile = (await client.post("/api/profiles", json={
        "name": "Startup in India", "context": {"country": "india", "edition": "Starter"},
    })).json()

    result = await verify(client, CLOUD_ANSWER, profile_id=profile["id"])
    assert result["context"]["country"] == "india"
    assert result["profile_version"] == 1

    updated = (await client.put(f"/api/profiles/{profile['id']}", json={
        "name": "Startup in Brazil", "context": {"country": "brazil", "edition": "Starter"},
    })).json()
    assert updated["version"] == 2

    profiles = (await client.get("/api/profiles")).json()["profiles"]
    assert [c["id"] for c in profiles[0]["drifted_checks"]] == [result["id"]]
    dashboard = (await client.get("/api/dashboard")).json()
    assert dashboard["drift"][0]["profile_name"] == "Startup in Brazil"

    renamed = (await client.put(f"/api/profiles/{profile['id']}", json={
        "name": "Renamed", "context": {"country": "brazil", "edition": "Starter"},
    })).json()
    assert renamed["version"] == 2


async def test_bad_country_is_rejected(client):
    response = await client.post("/api/profiles", json={"name": "x", "context": {"country": "atlantis"}})
    assert response.status_code == 422


# --- link rot ----------------------------------------------------------------------


async def test_link_check_classifies_evidence_links(client):
    result = await verify(client, CLOUD_ANSWER)

    body = (await client.post("/api/links/check", json={"check_id": result["id"]})).json()

    statuses = {item["url"]: item["status"] for item in body["results"]}
    assert statuses["https://technews.example/nimbus-price"] == "gone"
    assert statuses["https://dailycloud.example/nimbus"] == "moved"
    assert statuses["https://nimbus.example/docs/changelog"] == "changed"
    assert statuses["https://nimbus.example/pricing"] == "ok"
    assert body["counts"]["gone"] >= 1


async def test_link_check_refuses_private_addresses(monkeypatch):
    monkeypatch.setattr(links, "_public_only", True)

    report = await links.check_url("http://127.0.0.1:8000/api/health")

    assert report["status"] == "error" and "public" in report["detail"]


def test_urls_are_found_in_answer_text():
    assert links.urls_in_text("See https://a.example/x, and (https://b.example/y).") == [
        "https://a.example/x", "https://b.example/y",
    ]


# --- batch -------------------------------------------------------------------------


async def test_batch_checks_several_answers(client):
    started = (await client.post("/api/batch", json={"items": [
        {"answer": FACTS_ANSWER}, {"answer": CLOUD_ANSWER, "question": CLOUD_QUESTION},
    ]})).json()
    for _ in range(100):
        batch = (await client.get(f"/api/batch/{started['batch_id']}")).json()
        if batch["finished"]:
            break
        await asyncio.sleep(0.02)

    assert batch["finished"] and [item["status"] for item in batch["items"]] == ["done", "done"]
    assert (await client.get(f"/api/checks/{batch['items'][1]['check_id']}")).status_code == 200


# --- dashboard, system, evaluation, demo ---------------------------------------------


async def test_dashboard_summarises_saved_checks(client):
    await verify(client, FACTS_ANSWER)
    await verify(client, CLOUD_ANSWER)

    body = (await client.get("/api/dashboard")).json()

    assert body["totals"]["checks"] == 2
    assert body["totals"]["verdicts"]["stale"] >= 2
    assert body["daily"][-1]["checks"] == 2
    assert body["usage"]["llm_calls"] > 0
    assert body["alerts"][0]["kind"] == "withheld"
    assert {"pricing", "version_api"} <= set(body["by_category"])
    assert len((await client.get("/api/checks")).json()["checks"]) == 2


async def test_system_page_reports_services_and_cache(client, settings):
    settings.bifrost_setup_token = "token"

    body = (await client.get("/api/system")).json()

    assert body["bifrost"]["ok"] and body["tavily"]["ok"]
    assert body["cache_plugin"] == {"known": True, "enabled": True, "detail": "Enabled"}
    assert "provider-a" in body["settings"]["providers"]


async def test_cache_status_needs_an_admin_credential(client):
    body = (await client.get("/api/system")).json()
    assert body["cache_plugin"]["known"] is False
    assert (await client.post("/api/system/enable-cache")).status_code == 400


async def test_evaluation_page_without_results(client, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ROOT_DIR", tmp_path)
    assert (await client.get("/api/evaluation")).json() == {"available": False}


async def test_demo_mode_runs_with_no_keys(monkeypatch, settings):
    for name in ("_transport",):
        monkeypatch.setattr(llm, name, llm._transport)
        monkeypatch.setattr(search, name, search._transport)
        monkeypatch.setattr(links, name, links._transport)
    settings.demo_mode = True
    settings.tavily_api_key = ""
    settings.model_strong = ""

    demo.activate()

    assert settings.missing_required() == []
    assert settings.history_path.name == "history-demo.sqlite3"
    assert [s["id"] for s in demo.scenarios()] == ["cloud", "facts", "release", "history", "compare"]


# --- alerts ----------------------------------------------------------------------


async def test_stale_checks_send_a_webhook_alert(client, settings, monkeypatch):
    received = []
    monkeypatch.setattr(alerts, "_transport", httpx.MockTransport(
        lambda request: received.append(request) or httpx.Response(204)
    ))
    settings.alert_webhook_url = "https://hooks.example/shelflife"

    await verify(client, CLOUD_ANSWER)

    assert len(received) == 1
    import json
    payload = json.loads(received[0].content)
    assert payload["event"] == "stale_claims_found" and payload["stale_claims"]
