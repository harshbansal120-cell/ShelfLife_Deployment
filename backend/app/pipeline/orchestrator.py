"""Run the whole pipeline for one answer."""

from __future__ import annotations

import asyncio
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timezone
from typing import Any

from app import config, llm, policies
from app.authority import authority_for
from app.policies import FreshnessPolicy
from app.models import (
    ChangeInfo,
    CheckContext,
    CheckResult,
    Guard,
    Claim,
    ClaimResult,
    Evidence,
    ScoreBreakdown,
    Verdict,
)
from app.pipeline.adjudicate import Adjudication, AnswerSetting, adjudicate_claim, evidence_id
from app.pipeline.cascade import check_coupled_details
from app.pipeline.extract import extract_claims
from app.pipeline.independence import group_sources
from app.pipeline.metrics import MetricsCollector
from app.pipeline.reasoning import guard, resolve_derived
from app.pipeline.retrieve import retrieve_sources
from app.pipeline.rewrite import rewrite_answer
from app.pipeline.score import SourceInput, answer_score, score_claim, verdict_change_date
from app.pipeline.triage import triage
from app.search import SearchResult

EventHandler = Callable[[str, dict[str, Any]], Awaitable[None]]

BUDGET_MESSAGE = "The Bifrost budget for this app has run out."
NOT_ENOUGH_EVIDENCE = "There isn't enough recent, relevant evidence to score this claim."


class PipelineError(Exception):
    """The check couldn't run at all. Single-claim failures don't raise this."""

    def __init__(self, message: str, code: str = "pipeline_failed"):
        super().__init__(message)
        self.code = code


async def run_check(
    answer: str,
    *,
    question: str | None = None,
    answer_date: date | None = None,
    deep: bool = False,
    use_cache: bool = True,
    check_date: date | None = None,
    check_id: str | None = None,
    on_event: EventHandler | None = None,
    context: CheckContext | None = None,
    profile_id: str | None = None,
    profile_version: int | None = None,
    policy: FreshnessPolicy | None = None,
    trigger: str | None = None,
) -> CheckResult:
    settings = config.get_settings()
    policy = policy or policies.resolve(None)
    missing = settings.missing_required()
    if missing:
        raise PipelineError(f"Missing settings in .env: {', '.join(missing)}.", "not_configured")
    if not answer.strip():
        raise PipelineError("The answer is empty.", "invalid_input")

    check_date = check_date or date.today()
    metrics = MetricsCollector(use_cache=use_cache)

    async def emit(event: str, data: dict[str, Any]) -> None:
        if on_event is not None:
            await on_event(event, data)

    try:
        claims = await extract_claims(answer, question, answer_date, check_date, metrics)
    except llm.BudgetExceededError as exc:
        raise PipelineError(BUDGET_MESSAGE, "budget_exceeded") from exc
    except llm.LLMError as exc:
        raise PipelineError(f"Could not extract claims: {exc}", "extraction_failed") from exc
    await emit("claims_extracted", {"claims": [c.model_dump(mode="json") for c in claims]})

    async def emit_metrics() -> None:
        # Lets the UI show tokens, cost, cache hits and fallbacks while the check runs.
        await emit("metrics", metrics.snapshot().model_dump(mode="json"))

    await emit_metrics()
    results: dict[str, ClaimResult] = {}

    async def finish_claim(result: ClaimResult) -> None:
        results[result.claim.id] = result
        await emit("claim_scored", result.model_dump(mode="json"))

    # Every claim gets a claim_scored event, so the UI can settle each one as it lands.
    plan = triage(claims, settings.max_claims)
    for claim in plan.not_time_sensitive:
        await finish_claim(
            _unscored(claim, "not_time_sensitive", "This fact doesn't change over time.")
        )
    for claim in plan.over_limit:
        await finish_claim(
            _unscored(
                claim,
                "unverified",
                f"Not checked: answers are limited to {settings.max_claims} checked claims.",
            )
        )

    search_slots = asyncio.Semaphore(settings.tavily_concurrency)
    llm_slots = asyncio.Semaphore(settings.llm_concurrency)

    async def check_one(claim: Claim) -> ClaimResult:
        return await _check_claim(
            claim, check_date, answer_date, deep, search_slots, llm_slots, metrics, emit,
            context, policy, AnswerSetting(question, answer),
        )

    async def check(claim: Claim) -> None:
        await finish_claim(await check_one(claim))
        await emit_metrics()

    await asyncio.gather(*(check(claim) for claim in plan.to_check))
    # Details written about a value that turned out stale (its release date, say) are
    # re-checked for the current value, so the corrected answer stays consistent.
    coupled = await check_coupled_details(claims, results, answer, metrics, check_one)
    for result in coupled:
        await finish_claim(result)
    if coupled:
        await emit_metrics()
    # Calculations and recommendations, worked out from the checked facts.
    await resolve_derived(claims, answer, results, metrics, on_result=finish_claim)
    if plan.derived:
        await emit_metrics()

    ordered = [results[claim.id] for claim in claims]
    action, reason = guard(ordered, policy)
    rewrite = await rewrite_answer(answer, ordered, check_date, metrics)
    await emit("rewrite_ready", rewrite.model_dump(mode="json"))
    await emit_metrics()
    check_result = CheckResult(
        id=check_id or uuid.uuid4().hex,
        answer=answer,
        question=question,
        check_date=check_date,
        claims=ordered,
        answer_score=answer_score(
            (
                (item.claim.category, item.freshness_score)
                for item in ordered
                if item.freshness_score is not None
            ),
            policy.half_lives(),
        ),
        verdict_counts=dict(Counter(item.verdict for item in ordered)),
        corrected_answer=rewrite.corrected_answer,
        edits=rewrite.edits,
        citations=rewrite.citations,
        metrics=metrics.snapshot(),
        recheck_by=min((item.recheck_by for item in ordered if item.recheck_by), default=None),
        checked_at=datetime.now(timezone.utc),
        guard=Guard(action=action, reason=reason),
        context=context if context and not context.is_empty() else None,
        profile_id=profile_id,
        profile_version=profile_version,
        policy_id=policy.id,
        trigger=trigger,
    )
    await emit("done", check_result.model_dump(mode="json"))
    return check_result


async def _check_claim(
    claim: Claim,
    check_date: date,
    answer_date: date | None,
    deep: bool,
    search_slots: asyncio.Semaphore,
    llm_slots: asyncio.Semaphore,
    metrics: MetricsCollector,
    emit: EventHandler,
    context: CheckContext | None = None,
    policy: FreshnessPolicy | None = None,
    setting: AnswerSetting | None = None,
) -> ClaimResult:
    """Check one claim. A failure here marks this claim and never stops the others."""
    retrieved = await retrieve_sources(claim, search_slots, metrics, deep, context)
    if retrieved.all_failed:
        return _unscored(claim, "error", f"Web search failed: {retrieved.errors[0]}")

    sources = retrieved.sources
    await emit(
        "claim_evidence",
        {"claim_id": claim.id, "sources": [s.model_dump(mode="json") for s in sources]},
    )
    if not sources:
        return _unscored(claim, "unverified", "The web search found no sources for this claim.")

    try:
        async with llm_slots:
            adjudication = await adjudicate_claim(
                claim, sources, check_date, answer_date, metrics, context, setting
            )
    except llm.BudgetExceededError:
        return _unscored(claim, "error", f"{BUDGET_MESSAGE} This claim wasn't checked.")
    except llm.LLMValidationError:
        return _unscored(claim, "error", "The model returned invalid output twice.")
    except llm.LLMError as exc:
        return _unscored(claim, "error", f"The model call failed: {exc}")

    return assemble_result(claim, sources, adjudication, check_date, policy)


def assemble_result(
    claim: Claim,
    sources: list[SearchResult],
    adjudication: Adjudication,
    check_date: date,
    policy: FreshnessPolicy | None = None,
) -> ClaimResult:
    """Combine sources and stances, and score them in code."""
    half_life = policy.half_life(claim.category) if policy else None
    reference = scoring_date(claim, check_date)
    identifiers = [evidence_id(index) for index in range(len(sources))]
    authorities = [authority_for(source.domain, claim.entities) for source in sources]
    judgements = [adjudication.judgements[identifier] for identifier in identifiers]
    groups = group_sources(sources)

    inputs = [
        SourceInput(authority, source.published_date, judgement.stance, group)
        for authority, source, judgement, group in zip(authorities, sources, judgements, groups)
    ]
    score = score_claim(inputs, claim.category, reference, half_life)
    evidence = [
        Evidence(
            id=identifier,
            url=source.url,
            title=source.title,
            domain=source.domain,
            snippet=source.snippet,
            published_date=source.published_date,
            authority=scored.authority,
            recency=round(scored.recency, 4),
            weight=round(scored.weight, 4),
            stance=judgement.stance,
            quote=judgement.quote,
            favicon=source.favicon,
            group=group,
            counted=scored.counted,
            extracted=source.extracted,
        )
        for identifier, source, judgement, scored, group in zip(
            identifiers, sources, judgements, score.sources, groups
        )
    ]
    current_value = adjudication.current_value if score.score is not None else None
    explanation = adjudication.explanation
    if score.score is None or not explanation:
        explanation = NOT_ENOUGH_EVIDENCE if score.score is None else "Scored from the sources below."

    return ClaimResult(
        claim=claim,
        verdict=score.verdict,
        freshness_score=score.score,
        confidence=round(score.confidence, 4),
        current_value=current_value,
        explanation=explanation,
        evidence=evidence,
        score_breakdown=ScoreBreakdown(
            supporting_weight=round(score.supporting_weight, 4),
            contradicting_weight=round(score.contradicting_weight, 4),
            agreement=None if score.agreement is None else round(score.agreement, 4),
            best_recency=round(score.best_recency, 4),
            half_life_days=score.half_life_days,
            independent_sources=score.independent_sources,
        ),
        llm=adjudication.call,
        # History doesn't change, so a claim about a past time never needs re-checking.
        recheck_by=None if claim.historical else _recheck_by(
            inputs, claim.category, check_date, score.verdict, policy
        ),
        change=_change(score.verdict, current_value, adjudication, evidence),
        context_note=adjudication.context_note,
    )


def scoring_date(claim: Claim, check_date: date) -> date:
    """The day a claim's sources are aged against.

    A claim about now is judged by how recent its sources are. A claim about a past
    time is judged by sources from then or later: a page written after that time can
    report what was true then, so only sources from before it lose weight. With no
    date for the past time, no dated source loses weight for its age.
    """
    if claim.historical:
        return claim.as_of_date or date.min
    return check_date


def _recheck_by(
    inputs: list[SourceInput],
    category: str,
    check_date: date,
    verdict: str,
    policy: FreshnessPolicy | None,
) -> date | None:
    """When to look again: when the evidence ages out, or the policy's interval if sooner."""
    if verdict not in ("fresh", "uncertain"):
        return None
    half_life = policy.half_life(category) if policy else None
    dates = [
        verdict_change_date(inputs, category, check_date, half_life_days=half_life),
        policy.recheck_date(category, check_date) if policy else None,
    ]
    return min((day for day in dates if day), default=None)


CHANGE_TYPES = ("value_changed", "superseded", "deprecated", "discontinued", "renamed")


def _change(
    verdict: str, current_value: str | None, adjudication: Adjudication, evidence: list[Evidence]
) -> ChangeInfo | None:
    """Describe what changed, but only when a counted source contradicts the claim."""
    if verdict not in ("stale", "uncertain") or not current_value:
        return None
    contradicting = [e for e in evidence if e.stance == "contradicts" and e.counted]
    if not contradicting:
        return None
    best = max(contradicting, key=lambda item: item.weight)
    change_type = adjudication.change_type if adjudication.change_type in CHANGE_TYPES else "unclear"
    return ChangeInfo(
        change_type=change_type,
        old_value=adjudication.claimed_value,
        new_value=current_value,
        as_of=best.published_date,
        source_url=best.url,
    )


def _unscored(claim: Claim, verdict: Verdict, explanation: str) -> ClaimResult:
    return ClaimResult(
        claim=claim,
        verdict=verdict,
        freshness_score=None,
        confidence=0.0,
        current_value=None,
        explanation=explanation,
        evidence=[],
    )
