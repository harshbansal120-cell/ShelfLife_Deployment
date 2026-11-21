"""Re-check dates, change detection, Tavily Extract, history and /api/verify. Invented data."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import httpx
import pytest

from app import history, main
from app.jobs import CheckStore
from app.models import ChangeInfo
from app.pipeline.orchestrator import run_check
from app.pipeline.score import SourceInput, score_claim, verdict_change_date
from conftest import ANSWER, CEO_CLAIM, FOUNDING_CLAIM, PRICE_CLAIM

CHECK_DATE = date(2026, 1, 10)


def by_text(result):
    return {item.claim.text: item for item in result.claims}


# --- re-check dates ----------------------------------------------------------


def test_recheck_date_is_the_first_day_the_verdict_would_change():
    sources = [SourceInput(1.0, CHECK_DATE - timedelta(days=1), "supports")]

    due = verdict_change_date(sources, "pricing", CHECK_DATE)

    assert due is not None and due > CHECK_DATE
    assert score_claim(sources, "pricing", due).verdict != "fresh"
    assert score_claim(sources, "pricing", due - timedelta(days=1)).verdict == "fresh"


def test_recheck_date_matches_a_day_by_day_search():
    sources = [
        SourceInput(1.0, CHECK_DATE - timedelta(days=20), "supports"),
        SourceInput(0.4, CHECK_DATE - timedelta(days=5), "contradicts"),
    ]
    expected = next(
        CHECK_DATE + timedelta(days=days)
        for days in range(1, 2000)
        if score_claim(sources, "version_api", CHECK_DATE + timedelta(days=days)).verdict
        != score_claim(sources, "version_api", CHECK_DATE).verdict
    )

    assert verdict_change_date(sources, "version_api", CHECK_DATE) == expected


def test_slower_changing_facts_stay_fresh_longer():
    sources = [SourceInput(1.0, CHECK_DATE - timedelta(days=1), "supports")]

    assert verdict_change_date(sources, "law_regulation", CHECK_DATE) > verdict_change_date(
        sources, "pricing", CHECK_DATE
    )


@pytest.mark.parametrize(
    "sources",
    [
        pytest.param([SourceInput(1.0, CHECK_DATE, "contradicts")], id="already-stale"),
        pytest.param([], id="unverified"),
        pytest.param([SourceInput(1.0, None, "supports")], id="undated-sources-never-age"),
    ],
)
def test_no_recheck_date(sources):
    assert verdict_change_date(sources, "pricing", CHECK_DATE) is None


async def test_check_results_carry_recheck_dates(services):
    result = await run_check(ANSWER)

    claims = by_text(result)
    assert claims[CEO_CLAIM].recheck_by > result.check_date
    assert claims[PRICE_CLAIM].recheck_by is None
    assert claims[FOUNDING_CLAIM].recheck_by is None
    assert result.recheck_by == claims[CEO_CLAIM].recheck_by
    assert result.checked_at is not None


# --- what changed ------------------------------------------------------------


async def test_stale_claim_says_what_changed(services):
    services.adjudications[PRICE_CLAIM].update(
        claimed_value="$10 per month", change_type="value_changed"
    )

    change = by_text(await run_check(ANSWER))[PRICE_CLAIM].change

    assert change == ChangeInfo(
        change_type="value_changed",
        old_value="$10 per month",
        new_value="$25 per month",
        as_of=date.today() - timedelta(days=3),
        source_url="https://acme.example/pricing",
    )


async def test_unknown_change_type_is_invalid_output(services):
    services.adjudications[PRICE_CLAIM].update(change_type="whatever")

    # Invalid output is retried once, then the claim is marked as an error.
    assert by_text(await run_check(ANSWER))[PRICE_CLAIM].verdict == "error"


async def test_invented_old_value_is_dropped(services):
    services.adjudications[PRICE_CLAIM].update(
        claimed_value="$12 per month", change_type="superseded"
    )

    change = by_text(await run_check(ANSWER))[PRICE_CLAIM].change

    assert change.old_value is None
    assert change.change_type == "superseded"


async def test_markdown_report_shows_the_change_and_recheck_date(services):
    from app.export import to_markdown

    services.adjudications[PRICE_CLAIM].update(
        claimed_value="$10 per month", change_type="value_changed"
    )
    result = await run_check(ANSWER)

    report = to_markdown(result)

    assert "- What changed: value changed, $10 per month → $25 per month (as of" in report
    assert f"Re-check this answer by {result.recheck_by.isoformat()}." in report
    assert f"- Re-check by: {by_text(result)[CEO_CLAIM].recheck_by.isoformat()}" in report


async def test_fresh_claims_have_no_change(services):
    assert by_text(await run_check(ANSWER))[CEO_CLAIM].change is None


# --- Tavily Extract ----------------------------------------------------------


async def test_thin_official_page_is_read_in_full(services):
    page = "Plans. The Acme Cloud Starter plan now costs $25 per month, billed monthly. " * 3
    services.page_contents["https://acme.example/pricing"] = page

    result = await run_check(ANSWER)

    request = services.extract_requests[0]
    assert request["urls"] == ["https://acme.example/pricing"]
    assert request["query"] == "Acme Cloud monthly price"
    evidence = by_text(result)[PRICE_CLAIM].evidence[0]
    assert evidence.extracted is True
    assert evidence.snippet.startswith("Plans.")
    assert result.metrics.per_stage["retrieve"]["pages_read"] == 1
    assert result.metrics.tavily_credits == 3


async def test_only_thin_official_pages_in_some_categories_are_read(services):
    await run_check(ANSWER)

    # The CEO claim is about leadership, so its page isn't read.
    assert all("acme.example/about" not in str(r) for r in services.extract_requests)


async def test_extract_can_be_turned_off(services, settings):
    settings.use_tavily_extract = False

    await run_check(ANSWER)

    assert services.extract_requests == []


async def test_failed_extract_keeps_the_snippets(services, monkeypatch):
    from app import search

    async def broken(*args, **kwargs):
        raise search.SearchError("down")

    monkeypatch.setattr(search, "extract", broken)

    result = await run_check(ANSWER)

    assert by_text(result)[PRICE_CLAIM].evidence[0].extracted is False
    assert by_text(result)[PRICE_CLAIM].verdict == "stale"


async def test_extract_results_are_cached(services):
    services.page_contents["https://acme.example/pricing"] = "The Acme Cloud plan now costs $25 per month. " * 5

    await run_check(ANSWER)
    second = await run_check(ANSWER)

    assert len(services.extract_requests) == 1
    assert by_text(second)[PRICE_CLAIM].evidence[0].extracted is True


# --- history -----------------------------------------------------------------


def stamp(result, days_ago: int, answer: str | None = None):
    """A copy of a check, as if made earlier. Deep, so editing it can't touch the original."""
    return result.model_copy(
        update={
            "id": f"{result.id}-{days_ago}",
            "answer": answer or result.answer,
            "checked_at": datetime(2026, 1, 10, tzinfo=timezone.utc) - timedelta(days=days_ago),
        },
        deep=True,
    )


async def test_history_store_round_trip(services, settings):
    result = await run_check(ANSWER)
    store = history.HistoryStore(settings.history_path)

    store.save(stamp(result, 2))
    store.save(stamp(result, 1))
    store.save(stamp(result, 0, answer="Something else entirely."))

    assert store.get(stamp(result, 2).id).answer == ANSWER
    assert [r.id for r in store.for_answer("  acme cloud COSTS $10 per month. " + ANSWER[31:])] == [
        stamp(result, 1).id,
        stamp(result, 2).id,
    ]
    assert len(store.recent()) == 3


async def test_timeline_follows_each_claim_across_checks(services):
    current = await run_check(ANSWER)
    earlier = stamp(current, 5)
    earlier.claims[0] = earlier.claims[0].model_copy(update={"verdict": "fresh", "freshness_score": 88})

    timeline = history.claim_timeline(current, [earlier])

    assert [check["id"] for check in timeline["checks"]] == [earlier.id, current.id]
    price = next(c for c in timeline["claims"] if c["claim_text"] == PRICE_CLAIM)
    assert [entry["verdict"] for entry in price["entries"]] == ["fresh", "stale"]
    assert all(c["claim_text"] != FOUNDING_CLAIM for c in timeline["claims"])


async def test_watchlist_lists_claims_whose_evidence_is_getting_old(services):
    result = await run_check(ANSWER)
    ceo_due = by_text(result)[CEO_CLAIM].recheck_by

    soon = history.watchlist([result], ceo_due - timedelta(days=3), window_days=7)
    late = history.watchlist([result], ceo_due + timedelta(days=1), window_days=7)
    far = history.watchlist([result], ceo_due - timedelta(days=30), window_days=7)

    assert [(i["claim_text"], i["status"]) for i in soon] == [(CEO_CLAIM, "due_soon")]
    assert late[0]["status"] == "overdue"
    assert far == []


async def test_watchlist_uses_only_the_latest_check_of_each_answer(services):
    result = await run_check(ANSWER)
    due = by_text(result)[CEO_CLAIM].recheck_by

    items = history.watchlist([stamp(result, 3), stamp(result, 1)], due, window_days=0)

    assert {item["check_id"] for item in items} == {stamp(result, 1).id}


async def test_affected_answers_find_earlier_trusted_copies_of_a_stale_claim(services):
    current = await run_check(ANSWER)
    other = stamp(current, 4, answer="A different answer that mentioned Acme pricing.")
    other.claims[0] = other.claims[0].model_copy(update={"verdict": "fresh"})
    same_answer = stamp(current, 2)

    affected = history.affected_answers(current, [other, same_answer])

    price_id = by_text(current)[PRICE_CLAIM].claim.id
    assert list(affected) == [price_id]
    assert affected[price_id][0]["check_id"] == other.id


# --- API ---------------------------------------------------------------------


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setattr(main, "checks", CheckStore())
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as api:
        yield api


async def test_verify_returns_the_full_result_in_one_call(services, client):
    response = await client.post("/api/verify", json={"answer": ANSWER})

    assert response.status_code == 200
    assert response.json()["verdict_counts"]["stale"] == 1


async def test_verify_reports_a_failed_check(services, client):
    services.extraction = (402, {"type": "budget_exceeded", "error": {"message": "x"}})

    response = await client.post("/api/verify", json={"answer": ANSWER})

    assert response.status_code == 402
    assert "budget" in response.json()["detail"]


async def test_finished_checks_survive_a_restart(services, client, monkeypatch):
    check_id = (await client.post("/api/verify", json={"answer": ANSWER})).json()["id"]
    monkeypatch.setattr(main, "checks", CheckStore())

    assert (await client.get(f"/api/checks/{check_id}")).json()["id"] == check_id
    assert (await client.get(f"/api/checks/{check_id}/export")).status_code == 200


async def test_history_endpoint_compares_runs_of_the_same_answer(services, client):
    first = (await client.post("/api/verify", json={"answer": ANSWER})).json()["id"]
    second = (await client.post("/api/verify", json={"answer": ANSWER})).json()["id"]

    body = (await client.get(f"/api/checks/{second}/history")).json()

    assert [check["id"] for check in body["checks"]] == [first, second]
    assert all(len(claim["entries"]) == 2 for claim in body["claims"])


async def test_affected_and_watchlist_endpoints(services, client):
    check_id = (await client.post("/api/verify", json={"answer": ANSWER})).json()["id"]

    affected = (await client.get(f"/api/checks/{check_id}/affected")).json()
    watch = (await client.get("/api/watchlist?days=3650")).json()

    assert affected == {"claims": {}}
    assert [item["claim_text"] for item in watch["items"]] == [CEO_CLAIM]


async def test_unknown_check_history_is_404(client):
    assert (await client.get("/api/checks/nope/history")).status_code == 404
