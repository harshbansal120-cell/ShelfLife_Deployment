"""End-to-end tests of the pipeline and CLI against simulated services."""

from __future__ import annotations

import json

import httpx
import pytest

from app import cli
from app.pipeline.orchestrator import PipelineError, run_check
from conftest import ANSWER, CEO_CLAIM, FOUNDING_CLAIM, PRICE_CLAIM, extracted_claim


def by_text(result):
    return {item.claim.text: item for item in result.claims}


async def test_full_check_gives_each_claim_the_right_verdict(services):
    result = await run_check(ANSWER)

    claims = by_text(result)
    price = claims[PRICE_CLAIM]
    assert price.verdict == "stale"
    assert price.freshness_score == 0
    assert price.current_value == "$25 per month"
    assert price.evidence[0].stance == "contradicts"
    assert price.evidence[0].authority == 1.0
    assert price.score_breakdown.half_life_days == 90
    assert ANSWER[price.claim.span[0] : price.claim.span[1]] == "Acme Cloud costs $10 per month"

    ceo = claims[CEO_CLAIM]
    assert ceo.verdict == "fresh"
    assert ceo.freshness_score >= 90

    founding = claims[FOUNDING_CLAIM]
    assert founding.verdict == "not_time_sensitive"
    assert founding.evidence == []

    assert result.verdict_counts == {"stale": 1, "not_time_sensitive": 1, "fresh": 1}
    assert result.answer_score < 50
    assert [item.claim.id for item in result.claims] == ["c1", "c2", "c3"]


async def test_each_stage_uses_its_own_model_and_fallbacks(services):
    await run_check(ANSWER)

    extract_call = services.llm_requests[0]
    adjudicate_call = services.llm_requests[1]
    assert extract_call["model"] == "provider-a/fast"
    assert extract_call["fallbacks"] == ["provider-b/fast", "provider-c/fast"]
    assert adjudicate_call["model"] == "provider-a/strong"
    assert adjudicate_call["fallbacks"] == ["provider-b/strong"]


async def test_bifrost_cache_is_used_by_default(services, monkeypatch):
    headers = []
    original = services._llm

    def record(request):
        headers.append(request.headers.get("x-bf-cache-key"))
        return original(request)

    monkeypatch.setattr(services, "_llm", record)

    await run_check(ANSWER)

    assert headers and all(header for header in headers)


async def test_cache_can_be_skipped_so_every_call_reaches_a_provider(services, monkeypatch):
    headers = []
    original = services._llm

    def record(request):
        headers.append(request.headers.get("x-bf-cache-key"))
        return original(request)

    monkeypatch.setattr(services, "_llm", record)

    await run_check(ANSWER, use_cache=False)

    # Extraction, two adjudications and the rewrite.
    assert headers == [None, None, None, None]


async def test_static_claims_are_never_searched_and_official_domain_is_preferred(services):
    await run_check(ANSWER)

    assert {body["query"] for body in services.search_requests} == {
        "Acme Cloud monthly price",
        "Acme CEO",
    }
    pricing = next(b for b in services.search_requests if b["query"].startswith("Acme Cloud"))
    assert pricing["include_domains"] == ["acme.example"]
    assert pricing["include_domains_mode"] == "prefer"


async def test_metrics_cover_the_whole_check(services):
    services.extra_fields = {
        "routing_info": {
            "provider": "provider-b",
            "model": "strong",
            "is_fallback": True,
            "primary_provider": "provider-a",
            "primary_model": "strong",
        },
        "cache_debug": {"cache_hit": True, "hit_type": "direct"},
    }

    metrics = (await run_check(ANSWER)).metrics

    assert metrics.llm_calls == 4
    assert metrics.tokens_in == 400
    assert metrics.tokens_out == 80
    assert metrics.cache_hits == 4
    assert metrics.cost_usd == 0
    assert metrics.tavily_credits == 2
    assert metrics.per_stage["extract"]["calls"] == 1
    assert metrics.per_stage["adjudicate"]["calls"] == 2
    assert metrics.per_stage["rewrite"]["calls"] == 1
    assert metrics.per_stage["retrieve"]["searches"] == 2
    assert len(metrics.fallback_events) == 4
    assert metrics.fallback_events[0]["provider"] == "provider-b"


async def test_cost_marks_calls_it_cannot_price(services):
    metrics = (await run_check(ANSWER)).metrics

    assert metrics.unpriced_calls == 4
    assert metrics.cost_usd == 0


async def test_events_arrive_in_pipeline_order(services):
    events = []

    async def on_event(name, data):
        events.append((name, data))

    await run_check(ANSWER, on_event=on_event)

    names = [name for name, _ in events]
    assert names[0] == "claims_extracted"
    assert names[-1] == "done"
    assert names.count("claim_evidence") == 2
    assert names.count("claim_scored") == 3
    assert names[-2:] == ["metrics", "done"]
    assert names.index("rewrite_ready") > max(i for i, n in enumerate(names) if n == "claim_scored")
    # One after extraction, one after each checked claim, and one after the rewrite.
    assert names.count("metrics") == 4
    assert events[names.index("metrics")][1]["llm_calls"] == 1
    json.dumps([data for _, data in events])


async def test_each_claim_records_how_bifrost_served_it(services):
    services.extra_fields = {
        "routing_info": {
            "provider": "provider-b",
            "model": "strong",
            "is_fallback": True,
            "primary_provider": "provider-a",
            "primary_model": "strong",
        },
        "cache_debug": {"cache_hit": True, "hit_type": "direct"},
    }

    result = await run_check(ANSWER)

    call = by_text(result)[PRICE_CLAIM].llm
    assert call.served_by == "provider-b/strong"
    assert call.is_fallback is True
    assert call.primary_model == "provider-a/strong"
    assert call.cache_hit is True
    assert call.cache_hit_type == "direct"
    assert by_text(result)[FOUNDING_CLAIM].llm is None


async def test_invalid_model_output_marks_only_that_claim_as_error(services):
    services.adjudications[PRICE_CLAIM] = "this is not JSON"

    result = await run_check(ANSWER)

    claims = by_text(result)
    assert claims[PRICE_CLAIM].verdict == "error"
    assert claims[PRICE_CLAIM].freshness_score is None
    assert claims[CEO_CLAIM].verdict == "fresh"
    assert result.metrics.per_stage["adjudicate"]["calls"] == 3


async def test_retry_recovers_from_one_invalid_reply(services):
    services.adjudications[CEO_CLAIM] = ["not JSON", services.adjudications[CEO_CLAIM]]

    result = await run_check(ANSWER)

    assert by_text(result)[CEO_CLAIM].verdict == "fresh"
    assert result.metrics.per_stage["adjudicate"]["calls"] == 3


async def test_budget_exhaustion_is_explained_on_the_claim(services):
    services.adjudications[PRICE_CLAIM] = (402, {"type": "budget_exceeded", "error": {"message": "x"}})

    result = await run_check(ANSWER)

    assert by_text(result)[PRICE_CLAIM].verdict == "error"
    assert "budget" in by_text(result)[PRICE_CLAIM].explanation
    assert by_text(result)[CEO_CLAIM].verdict == "fresh"


async def test_claim_with_no_sources_is_unverified_without_an_llm_call(services):
    services.search_results["Acme CEO"] = []

    result = await run_check(ANSWER)

    assert by_text(result)[CEO_CLAIM].verdict == "unverified"
    # Extraction, the price claim's adjudication and the rewrite: none for the CEO claim.
    assert len(services.llm_requests) == 3
    assert not any(CEO_CLAIM in str(body) and "<claim>" in str(body) for body in services.llm_requests)


async def test_failed_search_is_an_error_not_a_verdict(services):
    services.search_results["Acme CEO"] = httpx.Response(500, json={"detail": "down"})

    result = await run_check(ANSWER)

    assert by_text(result)[CEO_CLAIM].verdict == "error"
    assert "search failed" in by_text(result)[CEO_CLAIM].explanation


async def test_weak_evidence_never_produces_a_verdict(services):
    services.search_results["Acme CEO"][0].update(
        url="https://reddit.com/r/acme/1", published_date=None
    )

    claim = by_text(await run_check(ANSWER))[CEO_CLAIM]

    assert claim.verdict == "unverified"
    assert claim.current_value is None


async def test_invented_quote_cannot_make_a_claim_fresh(services):
    services.adjudications[CEO_CLAIM]["judgements"][0]["quote"] = "Bo Lee runs everything at Acme"

    claim = by_text(await run_check(ANSWER))[CEO_CLAIM]

    assert claim.verdict == "unverified"
    assert claim.evidence[0].stance == "irrelevant"


async def test_claims_over_the_limit_are_reported_as_unchecked(services, settings):
    settings.max_claims = 1

    result = await run_check(ANSWER)

    assert by_text(result)[PRICE_CLAIM].verdict == "stale"
    assert by_text(result)[CEO_CLAIM].verdict == "unverified"
    assert "Not checked" in by_text(result)[CEO_CLAIM].explanation


async def test_answer_with_no_claims_is_a_valid_result(services):
    services.extraction = {"claims": []}

    result = await run_check("Hello there.")

    assert result.claims == []
    assert result.answer_score is None


async def test_answer_with_only_static_claims_has_no_score(services):
    services.extraction = {"claims": [extracted_claim(FOUNDING_CLAIM, "", "static")]}

    result = await run_check(ANSWER)

    assert result.answer_score is None
    assert services.search_requests == []


async def test_failed_extraction_stops_the_check_with_a_clear_error(services):
    services.extraction = "not JSON"

    with pytest.raises(PipelineError, match="Could not extract claims"):
        await run_check(ANSWER)


async def test_budget_exhausted_at_extraction(services):
    services.extraction = (402, {"type": "budget_exceeded", "error": {"message": "x"}})

    with pytest.raises(PipelineError, match="budget"):
        await run_check(ANSWER)


async def test_missing_model_is_named_before_any_call(services, settings):
    settings.model_strong = ""

    with pytest.raises(PipelineError, match="MODEL_STRONG"):
        await run_check(ANSWER)

    assert services.llm_requests == []


async def test_empty_answer_is_rejected(services):
    with pytest.raises(PipelineError, match="empty"):
        await run_check("   ")


# --- CLI ---------------------------------------------------------------------


def test_cli_prints_the_claim_table_and_summary(services, capsys):
    assert cli.main([ANSWER]) == 0

    output = capsys.readouterr().out
    assert "stale" in output
    assert "fresh" in output
    assert "not_time_sensitive" in output
    assert "Sources now say: $25 per month" in output
    assert "https://acme.example/pricing" in output
    assert "Answer freshness:" in output
    assert "Tavily: 2 credits" in output


def test_cli_json_output_is_a_full_result(services, capsys):
    assert cli.main([ANSWER, "--json"]) == 0

    data = json.loads(capsys.readouterr().out)
    assert data["answer"] == ANSWER
    assert len(data["claims"]) == 3


def test_cli_reads_a_file(services, capsys, tmp_path):
    path = tmp_path / "answer.txt"
    path.write_text(ANSWER, encoding="utf-8")

    assert cli.main(["--file", str(path)]) == 0
    assert "Answer freshness:" in capsys.readouterr().out


def test_cli_reports_missing_settings_and_fails(services, settings, capsys):
    settings.model_strong = ""

    assert cli.main([ANSWER]) == 1
    assert "MODEL_STRONG" in capsys.readouterr().err


def test_cli_requires_an_answer(capsys):
    with pytest.raises(SystemExit) as caught:
        cli.main([])

    assert caught.value.code == 2
