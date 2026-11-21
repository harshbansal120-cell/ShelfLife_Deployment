"""Tests for the check endpoints, event streaming and the answer generator."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app import llm, main
from app.jobs import CheckJob, CheckStore, TooManyChecksError
from app.models import CheckRequest
from app.pipeline import orchestrator
from conftest import ANSWER, PRICE_CLAIM

BUDGET_ERROR = (402, {"type": "budget_exceeded", "error": {"message": "x"}})


@pytest.fixture(autouse=True)
def store(monkeypatch) -> CheckStore:
    fresh = CheckStore()
    monkeypatch.setattr(main, "checks", fresh)
    return fresh


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as api:
        yield api


@pytest.fixture
def gated_check(monkeypatch):
    """Replace the pipeline with one that waits until the test releases it."""
    release = asyncio.Event()

    async def run_check(answer, *, on_event=None, **kwargs):
        await on_event("claims_extracted", {"claims": []})
        await release.wait()
        raise orchestrator.PipelineError("Stopped by the test.", "extraction_failed")

    monkeypatch.setattr(orchestrator, "run_check", run_check)
    return release


def parse_sse(text: str) -> list[dict]:
    events = []
    for block in text.split("\n\n"):
        fields = dict(
            line.split(": ", 1) for line in block.splitlines() if not line.startswith(":")
        )
        if fields:
            events.append(
                {
                    "id": int(fields["id"]),
                    "event": fields["event"],
                    "data": json.loads(fields["data"]),
                }
            )
    return events


async def start_check(client, **body) -> str:
    response = await client.post("/api/checks", json={"answer": ANSWER, **body})
    assert response.status_code == 202
    return response.json()["check_id"]


async def wait_until_finished(store: CheckStore, check_id: str) -> CheckJob:
    job = store.get(check_id)
    await job.task
    return job


# --- full flow ---------------------------------------------------------------


async def test_check_streams_progress_and_then_returns_the_result(services, client):
    check_id = await start_check(client)

    response = await client.get(f"/api/checks/{check_id}/events")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    events = parse_sse(response.text)
    names = [event["event"] for event in events]
    assert names[0] == "claims_extracted"
    assert names[-1] == "done"
    assert names.count("claim_evidence") == 2
    assert names.count("claim_scored") == 3
    assert [event["id"] for event in events] == list(range(1, len(events) + 1))

    final = await client.get(f"/api/checks/{check_id}")
    assert final.status_code == 200
    assert final.json() == events[-1]["data"]
    assert final.json()["id"] == check_id
    assert final.json()["verdict_counts"]["stale"] == 1


async def test_request_options_reach_the_pipeline(services, client, store):
    check_id = await start_check(
        client, question="What does Acme cost?", answer_date="2024-05-06", deep=True
    )
    job = await wait_until_finished(store, check_id)

    assert job.result.question == "What does Acme cost?"
    assert {body["search_depth"] for body in services.search_requests} == {"advanced"}
    assert "2024-05-06" in services.llm_requests[0]["messages"][1]["content"]


async def test_use_cache_reaches_the_pipeline(client, store, monkeypatch):
    seen = {}

    async def run_check(answer, **kwargs):
        seen.update(kwargs)
        raise orchestrator.PipelineError("stop", "extraction_failed")

    monkeypatch.setattr(orchestrator, "run_check", run_check)
    check_id = await start_check(client, use_cache=False)
    await store.get(check_id).task

    assert seen["use_cache"] is False


async def test_one_bad_claim_does_not_fail_the_check(services, client, store):
    services.adjudications[PRICE_CLAIM] = "not JSON"

    job = await wait_until_finished(store, await start_check(client))

    assert job.status == "done"
    assert job.result.verdict_counts["error"] == 1


# --- reconnecting ------------------------------------------------------------


async def test_late_client_gets_every_event(services, client, store):
    check_id = await start_check(client)
    job = await wait_until_finished(store, check_id)

    response = await client.get(f"/api/checks/{check_id}/events")

    assert len(parse_sse(response.text)) == len(job.events)


async def test_reconnect_resumes_after_the_last_event_seen(services, client, store):
    check_id = await start_check(client)
    job = await wait_until_finished(store, check_id)

    response = await client.get(
        f"/api/checks/{check_id}/events", headers={"Last-Event-ID": "2"}
    )

    assert [event["id"] for event in parse_sse(response.text)][0] == 3
    assert parse_sse(response.text)[-1]["id"] == len(job.events)


async def test_reconnect_after_everything_was_seen_tells_the_browser_to_stop(
    services, client, store
):
    check_id = await start_check(client)
    job = await wait_until_finished(store, check_id)

    response = await client.get(
        f"/api/checks/{check_id}/events", headers={"Last-Event-ID": str(len(job.events))}
    )

    assert response.status_code == 204


async def test_invalid_last_event_id_replays_from_the_start(services, client, store):
    check_id = await start_check(client)
    job = await wait_until_finished(store, check_id)

    response = await client.get(
        f"/api/checks/{check_id}/events", headers={"Last-Event-ID": "abc"}
    )

    assert len(parse_sse(response.text)) == len(job.events)


# --- failures and limits -----------------------------------------------------


async def test_failed_check_reports_an_error_event_and_status(services, client):
    services.extraction = "not JSON"
    check_id = await start_check(client)

    events = parse_sse((await client.get(f"/api/checks/{check_id}/events")).text)

    assert [event["event"] for event in events] == ["error"]
    assert events[0]["data"]["code"] == "extraction_failed"
    final = await client.get(f"/api/checks/{check_id}")
    assert final.status_code == 500
    assert final.json()["status"] == "failed"
    assert final.json()["error"]["code"] == "extraction_failed"


async def test_exhausted_budget_has_its_own_error_code(services, client):
    services.extraction = BUDGET_ERROR
    check_id = await start_check(client)

    events = parse_sse((await client.get(f"/api/checks/{check_id}/events")).text)

    assert events[0]["data"]["code"] == "budget_exceeded"
    assert "budget" in events[0]["data"]["message"]


async def test_unexpected_crash_does_not_leak_details(client, monkeypatch):
    async def run_check(*args, **kwargs):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(orchestrator, "run_check", run_check)
    check_id = await start_check(client)

    event = parse_sse((await client.get(f"/api/checks/{check_id}/events")).text)[0]

    assert event["data"]["code"] == "internal_error"
    assert "secret" not in json.dumps(event)


async def test_running_check_returns_202(client, store, gated_check):
    check_id = await start_check(client)
    await asyncio.sleep(0)

    response = await client.get(f"/api/checks/{check_id}")

    assert response.status_code == 202
    assert response.json() == {"check_id": check_id, "status": "running"}
    gated_check.set()
    await store.get(check_id).task


async def test_too_many_running_checks_are_refused(client, store, gated_check):
    store.max_active = 1
    check_id = await start_check(client)

    response = await client.post("/api/checks", json={"answer": ANSWER})

    assert response.status_code == 429
    gated_check.set()
    await store.get(check_id).task


async def test_missing_settings_are_reported_before_starting(client, settings, store):
    settings.model_strong = ""

    response = await client.post("/api/checks", json={"answer": ANSWER})

    assert response.status_code == 503
    assert "MODEL_STRONG" in response.json()["detail"]
    assert store._jobs == {}


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({}, id="missing"),
        pytest.param({"answer": "   "}, id="blank"),
        pytest.param({"answer": "x" * 20_001}, id="too-long"),
        pytest.param({"answer": "x", "answer_date": "soon"}, id="bad-date"),
        pytest.param({"answer": "x", "question": "q" * 2_001}, id="question-too-long"),
    ],
)
async def test_invalid_requests_are_rejected(client, body):
    assert (await client.post("/api/checks", json=body)).status_code == 422


def test_blank_question_is_treated_as_absent():
    assert CheckRequest(answer="x", question="  ").question is None


@pytest.mark.parametrize("path", ["/api/checks/nope", "/api/checks/nope/events"])
async def test_unknown_check_is_404(client, path):
    assert (await client.get(path)).status_code == 404


async def test_browser_app_is_allowed_by_cors(client):
    response = await client.options(
        "/api/checks",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


async def test_other_origins_are_not_allowed_by_cors(client):
    response = await client.get("/api/checks/nope", headers={"Origin": "http://evil.test"})

    assert "access-control-allow-origin" not in response.headers


# --- job streaming -----------------------------------------------------------


async def next_item(stream):
    return await asyncio.wait_for(anext(stream), 1)


async def test_stream_delivers_events_as_they_are_published():
    job = CheckJob("c")
    stream = job.stream()
    pending = asyncio.ensure_future(next_item(stream))
    await asyncio.sleep(0)
    assert not pending.done()

    job.publish("first", {})

    assert (await pending).name == "first"
    await stream.aclose()


async def test_every_subscriber_gets_every_event():
    job = CheckJob("c")
    first, second = job.stream(), job.stream()
    pending = [asyncio.ensure_future(next_item(item)) for item in (first, second)]
    await asyncio.sleep(0)

    job.publish("event", {})

    assert [(await item).name for item in pending] == ["event", "event"]
    await first.aclose()
    await second.aclose()


async def test_quiet_stream_yields_keep_alives():
    job = CheckJob("c")
    stream = job.stream(heartbeat_seconds=0.01)

    assert await next_item(stream) is None
    await stream.aclose()


async def test_stream_ends_when_the_job_fails():
    job = CheckJob("c")
    job.fail("code", "message")

    assert [event.name async for event in job.stream()] == ["error"]


async def test_disconnecting_does_not_stop_the_check(client, store, gated_check):
    check_id = await start_check(client)
    await asyncio.sleep(0)
    job = store.get(check_id)
    stream = job.stream()
    await next_item(stream)

    await stream.aclose()

    assert job._waiters == set()
    assert not job.task.done()
    gated_check.set()
    await job.task
    assert job.status == "failed"


# --- store -------------------------------------------------------------------


async def test_oldest_finished_checks_are_evicted(services):
    store = CheckStore(max_active=5, max_stored=2)
    first = store.start(CheckRequest(answer=ANSWER))
    await first.task
    second = store.start(CheckRequest(answer=ANSWER))
    await second.task
    third = store.start(CheckRequest(answer=ANSWER))
    await third.task

    assert store.get(first.id) is None
    assert store.get(second.id) is second
    assert store.get(third.id) is third


async def test_store_refuses_work_over_the_limit(gated_check):
    store = CheckStore(max_active=1)
    job = store.start(CheckRequest(answer=ANSWER))

    with pytest.raises(TooManyChecksError):
        store.start(CheckRequest(answer=ANSWER))

    gated_check.set()
    await job.task


async def test_shutdown_marks_running_checks_as_cancelled(gated_check):
    store = CheckStore()
    job = store.start(CheckRequest(answer=ANSWER))
    await asyncio.sleep(0)

    await store.shutdown()

    assert job.status == "failed"
    assert job.error["code"] == "cancelled"


# --- budget ------------------------------------------------------------------


def quota_transport(monkeypatch, status_code, payload):
    def handler(request):
        assert request.url.path == "/api/governance/virtual-keys/quota"
        return httpx.Response(status_code, json=payload)

    monkeypatch.setattr(llm, "_transport", httpx.MockTransport(handler))


async def test_budget_reports_the_virtual_key_spend(client, monkeypatch):
    quota_transport(
        monkeypatch,
        200,
        {
            "virtual_key_name": "shelflife",
            "budgets": [{"max_limit": 5, "current_usage": 1.5, "reset_duration": "1M"}],
        },
    )

    body = (await client.get("/api/budget")).json()

    assert body["configured"] is True
    assert body["budgets"] == [{"max_limit": 5, "current_usage": 1.5, "reset_duration": "1M"}]


async def test_budget_explains_a_rejected_key(client, monkeypatch):
    quota_transport(monkeypatch, 401, {"type": "access_not_found", "error": {"message": "no"}})

    response = await client.get("/api/budget")

    assert response.status_code == 502
    assert "BIFROST_VK" in response.json()["detail"]


# --- generate-stale ----------------------------------------------------------


async def test_generate_stale_uses_the_old_model(services, client):
    services.extraction = "  Acme Cloud costs $10 per month.  "

    response = await client.post("/api/generate-stale", json={"question": "Acme price?"})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Acme Cloud costs $10 per month."
    assert body["model"] == "provider-a/old"
    assert body["is_fallback"] is False
    assert services.llm_requests[0]["model"] == "provider-a/old"
    assert "<question>\nAcme price?\n</question>" in services.llm_requests[0]["messages"][1]["content"]


async def test_generate_stale_reports_the_fallback_that_served_it(services, client):
    services.extraction = "An answer."
    services.extra_fields = {
        "routing_info": {"provider": "provider-b", "model": "fast", "is_fallback": True}
    }

    body = (await client.post("/api/generate-stale", json={"question": "Q?"})).json()

    assert body["model"] == "provider-b/fast"
    assert body["is_fallback"] is True


@pytest.mark.parametrize(
    ("reply", "expected_status"),
    [
        pytest.param(BUDGET_ERROR, 402, id="budget"),
        pytest.param((500, {"error": {"message": "down"}}), 502, id="gateway-error"),
        pytest.param("   ", 502, id="empty-answer"),
    ],
)
async def test_generate_stale_failures(services, client, reply, expected_status):
    services.extraction = reply

    response = await client.post("/api/generate-stale", json={"question": "Q?"})

    assert response.status_code == expected_status


async def test_generate_stale_needs_its_model(services, client, settings):
    settings.model_stale = ""

    response = await client.post("/api/generate-stale", json={"question": "Q?"})

    assert response.status_code == 503
    assert "MODEL_STALE" in response.json()["detail"]
    assert services.llm_requests == []
