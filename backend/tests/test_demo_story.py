"""The whole pipeline on the demo scenarios: assumptions, numbers, decisions, APIs, availability."""

from __future__ import annotations

import httpx
import pytest

from app import links, llm, search
from app.demo.simulator import CLOUD_ANSWER, FACTS_ANSWER, Simulator
from app.models import CheckContext
from app.pipeline.orchestrator import run_check


@pytest.fixture
def simulator(monkeypatch):
    fake = Simulator(latency=(0, 0))
    transport = httpx.MockTransport(fake)
    monkeypatch.setattr(llm, "_transport", transport)
    monkeypatch.setattr(search, "_transport", transport)
    monkeypatch.setattr(links, "_transport", transport)
    monkeypatch.setattr(links, "_public_only", False)
    return fake


def by_kind(result, kind):
    return [item for item in result.claims if item.claim.kind == kind]


def by_start(result, text):
    return next(item for item in result.claims if item.claim.text.startswith(text))


async def test_cloud_story_end_to_end(simulator):
    result = await run_check(CLOUD_ANSWER, context=CheckContext(country="india"))

    price = by_start(result, "Nimbus Cloud's Starter plan costs")
    assert price.verdict == "stale"
    assert price.change.old_value == "$20 per seat per month"
    assert price.evidence[0].extracted is True
    assert price.score_breakdown.independent_sources < len([e for e in price.evidence if e.stance != "irrelevant"])

    total = by_start(result, "For 10 seats")
    assert total.claim.kind == "calculation"
    assert total.verdict == "stale"
    assert total.recalculation.stated == 200 and total.recalculation.recomputed == 280
    assert total.change.new_value == "$280"

    saving = by_start(result, "Choosing Nimbus Cloud saves")
    assert saving.recalculation.recomputed == -30
    assert saving.verdict == "stale"

    assumption = by_kind(result, "assumption")[0]
    assert assumption.claim.span is None
    assert assumption.verdict == "stale"

    recommendation = by_kind(result, "recommendation")[0]
    assert recommendation.verdict == "stale"
    assert recommendation.decision.holds == "no"
    assert "Stratus Cloud" in recommendation.decision.revised
    assert set(recommendation.affected_by) >= {price.claim.id, total.claim.id, assumption.claim.id}

    api = by_kind(result, "api_usage")[0]
    assert api.verdict == "stale" and api.change.change_type == "deprecated"
    assert api.change.new_value == "nimbus.deployments.create(app)"

    availability = by_kind(result, "availability")[0]
    assert availability.verdict == "fresh" and availability.context_note is None

    assert result.guard.action == "withhold"
    assert "Stratus Cloud is now the cheaper option" in result.corrected_answer
    assert "$280" in result.corrected_answer
    assert "nimbus.deployments.create(app)" in result.corrected_answer
    assert result.context.country == "india"
    assert all(item.claim.passport_id.startswith("CLM-") for item in result.claims)


async def test_context_can_make_a_true_claim_wrong_for_the_reader(simulator):
    result = await run_check(CLOUD_ANSWER, context=CheckContext(country="brazil"))

    availability = by_kind(result, "availability")[0]
    assert availability.context_note == "No Brazil region is listed."


async def test_country_reaches_tavily_for_local_claims(simulator, monkeypatch):
    bodies = []
    original = search._post

    async def record(path, body, key):
        bodies.append(body)
        return await original(path, body, key)

    monkeypatch.setattr(search, "_post", record)

    await run_check(CLOUD_ANSWER, context=CheckContext(country="india"))

    pricing = [b for b in bodies if b.get("query", "").startswith("Stratus Cloud price")]
    assert pricing and pricing[0]["country"] == "india" and pricing[0]["query"].endswith("India")


async def test_facts_scenario_gives_every_verdict(simulator):
    result = await run_check(FACTS_ANSWER)

    verdicts = {item.verdict for item in result.claims}
    assert {"stale", "uncertain", "fresh", "unverified", "error", "not_time_sensitive"} <= verdicts
    assert result.guard.action == "show_with_warning"


def test_unknown_country_is_rejected():
    with pytest.raises(ValueError):
        CheckContext(country="atlantis")


async def test_demo_link_check_visits_only_invented_sites(simulator, monkeypatch):
    monkeypatch.setattr(links, "_demo_suffix", ".example")
    results = await links.check_links([
        {"url": "https://nimbus.example/pricing", "quote": "$28 per seat per month"},
        {"url": "https://technews.example/nimbus-price"},
        {"url": "https://dailycloud.example/nimbus"},
        {"url": "https://oldblog.example/cheap-clouds"},
        {"url": "https://www.example.com/real-site"},
    ])
    statuses = {item["url"]: item["status"] for item in results}
    assert statuses["https://nimbus.example/pricing"] == "ok"
    assert statuses["https://technews.example/nimbus-price"] == "gone"
    assert statuses["https://dailycloud.example/nimbus"] == "moved"
    assert statuses["https://oldblog.example/cheap-clouds"] == "gone"
    real = next(item for item in results if item["url"] == "https://www.example.com/real-site")
    assert real["status"] == "error" and ".example sites" in real["detail"]
