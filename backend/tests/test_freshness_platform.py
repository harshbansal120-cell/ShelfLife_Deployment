"""Coupled details, freshness policies, downstream impact, the dependency graph, the
autopilot agent and the MCP endpoint, end to end on the built-in simulator."""

from __future__ import annotations

from datetime import date, timedelta

import httpx
import pytest

from app import agent, demo, impact, links, llm, main, policies, search, workspace
from app.demo.simulator import (
    CLOUD_ANSWER,
    FACTS_ANSWER,
    ORION_44_RELEASED,
    RELEASE_ANSWER,
    SEED_DOCUMENTS,
    Simulator,
    long_date,
)
from app.jobs import CheckStore
from app.models import CheckContext
from app.passport import passport_id
from app.pipeline import cascade
from app.pipeline.orchestrator import run_check
from app import history


@pytest.fixture
def simulator(monkeypatch):
    fake = Simulator(latency=(0, 0))
    transport = httpx.MockTransport(fake)
    for module in (llm, search, links):
        monkeypatch.setattr(module, "_transport", transport)
    monkeypatch.setattr(links, "_public_only", False)
    monkeypatch.setattr(links, "_demo_suffix", ".example")
    return fake


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setattr(main, "checks", CheckStore())
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as api:
        yield api


def by_id(result, claim_id):
    return next(item for item in result.claims if item.claim.id == claim_id)


# --- details of a stale value ---------------------------------------------------------


async def test_a_release_date_written_beside_a_stale_version_is_rechecked_and_corrected(simulator):
    result = await run_check(RELEASE_ANSWER)

    version, launched, support = (by_id(result, cid) for cid in ("c1", "c2", "c3"))
    assert version.verdict == "stale" and version.current_value == "version 4.4"
    # On its own "Orion 4.2 was launched on March 4, 2025" never goes stale. In the
    # answer it describes "the latest release", so it was checked for 4.4.
    assert launched.coupled_to == "c1"
    assert launched.checked_as == "Orion 4.4 was launched on March 4, 2025."
    assert launched.verdict == "stale"
    assert launched.current_value == long_date(ORION_44_RELEASED)
    assert launched.evidence and launched.evidence[0].url.endswith("orion-4-4")
    assert launched.affected_by == ["c1"]
    assert support.verdict == "stale" and support.current_value == "1.x, 2.x and 3.x"

    corrected = result.corrected_answer
    assert f"version 4.4, launched on {long_date(ORION_44_RELEASED)}" in corrected
    assert "March 4, 2025" not in corrected and "4.2" not in corrected
    assert "Orion 1.x, 2.x and 3.x are no longer supported" in corrected
    merged = next(edit for edit in result.edits if "c1" in edit.claim_ids)
    assert merged.claim_ids == ["c1", "c2"] and len(merged.citations) == 2


def test_a_detail_that_names_the_old_thing_explicitly_is_not_coupled():
    from app.models import Claim, ClaimResult

    anchor = ClaimResult(
        claim=Claim(id="c1", text="The latest release is 3.13.", span=(0, 26), category="version_api",
                    entities=[], time_sensitive=True, search_queries=[]),
        verdict="stale", freshness_score=0, confidence=1, current_value="3.15", explanation="", evidence=[],
    )
    separate = Claim(id="c2", text="Python 3.13 added a JIT.", span=(28, 52), category="static",
                     entities=[], time_sensitive=False, search_queries=[])
    results = {"c1": anchor, "c2": ClaimResult(claim=separate, verdict="not_time_sensitive", freshness_score=None,
                                               confidence=0, current_value=None, explanation="", evidence=[])}

    assert cascade.find_couplings([anchor.claim, separate], results) == []
    linked = separate.model_copy(update={"depends_on": ["c1"]})
    assert [c.detail.id for c in cascade.find_couplings([anchor.claim, linked], results)] == ["c2"]


def test_without_the_model_a_detail_is_restated_by_swapping_the_number():
    from app.models import ChangeInfo, Claim, ClaimResult

    anchor = ClaimResult(
        claim=Claim(id="c1", text="The latest stable release of Python is version 3.13.", span=(0, 51),
                    category="version_api", entities=["Python"], time_sensitive=True, search_queries=[]),
        verdict="stale", freshness_score=0, confidence=1, current_value="Python 3.15", explanation="",
        evidence=[], change=ChangeInfo(change_type="superseded", old_value="version 3.13",
                                       new_value="Python 3.15", as_of=None, source_url=None),
    )

    assert cascade.substitute("Python 3.13 was launched on October 7, 2024.", anchor) == (
        "Python 3.15 was launched on October 7, 2024."
    )
    # 3.130 is not 3.13.
    assert cascade.substitute("Python 3.130 shipped.", anchor) is None


# --- freshness policies ------------------------------------------------------------------


async def test_a_policy_changes_half_lives_recheck_dates_and_the_guard(simulator):
    balanced = await run_check(FACTS_ANSWER, policy=policies.get_policy("balanced"))
    developer = await run_check(FACTS_ANSWER, policy=policies.get_policy("developer"))
    production = await run_check(RELEASE_ANSWER, policy=policies.get_policy("production_api"))

    sdk_balanced = next(i for i in balanced.claims if "Acme SDK" in i.claim.text)
    sdk_developer = next(i for i in developer.claims if "Acme SDK" in i.claim.text)
    assert sdk_balanced.score_breakdown.half_life_days == 120
    assert sdk_developer.score_breakdown.half_life_days == 30
    # The only source is 210 days old: usable at a 120-day half-life, but seven
    # half-lives old for a developer assistant, so it can no longer vouch for the claim.
    assert sdk_balanced.verdict == "uncertain"
    assert sdk_developer.verdict == "unverified" and sdk_developer.freshness_score is None
    assert developer.policy_id == "developer"

    ceo = next(i for i in developer.claims if "CEO" in i.claim.text)
    assert ceo.recheck_by is not None
    business = await run_check(FACTS_ANSWER, policy=policies.get_policy("business"))
    ceo_business = next(i for i in business.claims if "CEO" in i.claim.text)
    # Leadership is re-verified daily under the business policy.
    assert ceo_business.recheck_by == date.today() + timedelta(days=1)

    assert production.guard.action == "withhold"
    assert "Production API policy" in production.guard.reason


def test_presets_are_read_only_and_custom_policies_are_validated():
    with pytest.raises(PermissionError):
        policies.delete_policy("balanced")
    custom = policies.save_policy(policies.PolicyRequest(
        name="Docs bot", half_life_days={"version_api": 14}, recheck_days={"version_api": 2},
        withhold_categories=["version_api"],
    ))
    assert policies.get_policy(custom.id).half_life("version_api") == 14
    assert policies.get_policy(custom.id).half_life("pricing") == 90
    policies.set_default(custom.id)
    assert policies.resolve(None).id == custom.id
    policies.delete_policy(custom.id)
    assert policies.resolve(None).id == "balanced"
    with pytest.raises(ValueError):
        policies.PolicyRequest(name="Bad", half_life_days={"astrology": 3})


# --- downstream impact and the graph -----------------------------------------------------------


async def _seeded_workspace():
    await demo.seed()
    for answer, context in ((CLOUD_ANSWER, CheckContext(country="india")), (RELEASE_ANSWER, None), (FACTS_ANSWER, None)):
        history.store().save(await run_check(answer, context=context))


async def test_a_stale_price_is_traced_to_every_document_built_on_it(simulator):
    await _seeded_workspace()

    price = passport_id("Nimbus Cloud's Starter plan costs $20 per seat per month.")
    report = impact.impact_report(price)

    assert report["claim"]["status"] == "stale"
    titles = {doc["title"] for doc in report["documents"]}
    assert titles == {"Kestrel Labs hosting proposal", "FY hosting budget projection",
                      "Welcome email to Priya at Kestrel Labs"}
    assert {d["kind"] for d in report["dependents"]} >= {"calculation", "recommendation"}
    assert report["severity"] == "high"


async def test_a_document_gets_a_corrected_version_with_recalculated_figures(simulator):
    await _seeded_workspace()
    projection = next(d for d in impact.list_documents() if d["kind"] == "projection")

    analysis = await impact.analyze_document(projection)

    assert analysis["status"] == "needs_update"
    assert "$28 per seat per month" in analysis["corrected_text"]
    # 10 seats x 12 months x $28, recomputed in code.
    assert "$3,360 a year" in analysis["corrected_text"]
    assert "$20" not in analysis["corrected_text"]
    assert analysis["citations"]


async def test_declared_dependencies_cross_answers(simulator):
    await _seeded_workspace()

    runtime = passport_id("The latest stable release of the Orion runtime is version 4.2.")
    report = impact.impact_report(runtime)

    sdk = passport_id("The latest Acme SDK is version 3.2.")
    assert any(d["passport_id"] == sdk and d["relation"] == "declared" for d in report["dependents"])
    assert any(d["relation"] == "describes" for d in report["dependents"])
    assert "Platform upgrade plan" in {doc["title"] for doc in report["documents"]}

    with pytest.raises(ValueError):
        impact.add_edge(impact.EdgeRequest(upstream=sdk, downstream=runtime))

    graph = impact.graph()
    assert graph["stats"]["documents"] == len(SEED_DOCUMENTS)
    assert graph["hot"][0]["reach"] >= graph["hot"][-1]["reach"]


# --- the autopilot -----------------------------------------------------------------------------


async def test_one_cycle_verifies_traces_and_corrects_without_being_asked(simulator):
    await demo.seed()
    history.store().save(await run_check(CLOUD_ANSWER, context=CheckContext(country="india")))

    summary = await agent.autopilot.run_cycle("auto")

    assert summary["actions"] > 0
    log = agent.events(200)
    kinds = {event["kind"] for event in log}
    assert {"cycle", "links", "impact", "document"} <= kinds
    updated = [d for d in impact.list_documents() if d["revisions"]]
    assert {d["kind"] for d in updated} >= {"proposal", "projection", "email"}
    projection = next(d for d in updated if d["kind"] == "projection")
    assert "$3,360 a year" in projection["text"]
    assert projection["revisions"][0]["by"] == "autopilot"
    assert "$2,400" in projection["revisions"][0]["previous_text"]


async def test_repeated_cycles_settle_instead_of_correcting_again(simulator):
    await demo.seed()
    history.store().save(await run_check(CLOUD_ANSWER, context=CheckContext(country="india")))

    for _ in range(4):
        await agent.autopilot.run_cycle("auto")

    documents = impact.list_documents()
    index = impact.build_index()
    for document in documents:
        # A corrected document states the new values; it must not match the old stale
        # claims again and be "corrected" a second time.
        assert len(document["revisions"]) <= 1, document["title"]
        assert impact.quick_status(document, index) != "needs_update", document["title"]
        assert "(now" not in document["text"]
    email = next(d for d in documents if d["kind"] == "email")
    assert email["text"].count("nimbus.deployments.create(app)") == 1


def test_a_claim_stating_the_correction_does_not_match_the_stale_original():
    from app.models import ChangeInfo, Claim, ClaimResult

    stale = ClaimResult(
        claim=Claim(id="c1", text="nimbus.deploy(app) is the current way to deploy with the Nimbus SDK.",
                    span=None, category="version_api", entities=[], time_sensitive=True, search_queries=[]),
        verdict="stale", freshness_score=0, confidence=1, current_value="nimbus.deployments.create(app)",
        explanation="", evidence=[], change=ChangeInfo(change_type="deprecated", old_value="nimbus.deploy(app)",
                                                       new_value="nimbus.deployments.create(app)", as_of=None, source_url=None),
    )
    corrected = "nimbus.deployments.create(app) is the current way to deploy with the Nimbus SDK."

    assert not impact.states_same_value(corrected, stale)
    assert impact.states_same_value(stale.claim.text, stale)


async def test_autopilot_settings_are_saved(client):
    response = await client.put("/api/autopilot", json={"mode": "auto", "interval_seconds": 60})

    assert response.status_code == 200
    assert response.json()["mode"] == "auto"
    assert agent.get_settings().interval_seconds == 60
    assert (await client.put("/api/autopilot", json={"mode": "sideways"})).status_code == 422


# --- MCP -----------------------------------------------------------------------------------------


async def test_mcp_lists_and_calls_tools(simulator, client):
    init = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                           "params": {"protocolVersion": "2025-06-18"}})
    assert init.json()["result"]["serverInfo"]["name"] == "shelflife"
    note = await client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert note.status_code == 202

    listed = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {tool["name"] for tool in listed.json()["result"]["tools"]}
    assert {"verify_answer", "impact_of_claim", "register_document", "autopilot"} <= names

    called = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
        "name": "verify_answer", "arguments": {"answer": RELEASE_ANSWER}}})
    output = called.json()["result"]
    assert output["isError"] is False
    assert output["structuredContent"]["guard"]["action"] == "withhold"
    assert "version 4.4" in output["structuredContent"]["corrected_answer"]

    missing = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
        "name": "impact_of_claim", "arguments": {"passport_id": "CLM-000000"}}})
    assert missing.json()["result"]["isError"] is True
    unknown = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 5, "method": "nope"})
    assert unknown.json()["error"]["code"] == -32601


async def test_documents_api_registers_and_reports(simulator, client):
    history.store().save(await run_check(CLOUD_ANSWER, context=CheckContext(country="india")))
    response = await client.post("/api/documents", json={
        "title": "Quote", "kind": "email", "text": SEED_DOCUMENTS[2]["text"],
    })
    assert response.status_code == 201
    document = response.json()
    assert document["status"] == "needs_update"
    assert any(link["status"] == "stale" for link in document["links"])

    applied = (await client.post(f"/api/documents/{document['id']}/apply")).json()
    assert "nimbus.deployments.create(app)" in applied["text"]
    assert applied["revisions"][0]["by"] == "user"

    impacts = (await client.get("/api/impact")).json()["items"]
    assert impacts and impacts[0]["counts"]["total"] >= impacts[-1]["counts"]["total"]
    assert (await client.get("/api/graph")).status_code == 200
    assert (await client.get("/api/policies")).json()["default"] == "balanced"


def test_workspace_settings_round_trip():
    workspace.set_setting("x", {"a": 1})
    assert workspace.get_setting("x") == {"a": 1}
    assert workspace.get_setting("missing", 5) == 5
