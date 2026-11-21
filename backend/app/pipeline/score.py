"""The freshness score. Pure functions only: no I/O and no LLM opinions."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from app.config import (
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_SCALE,
    FRESH_THRESHOLD,
    HALF_LIFE_DAYS,
    MIN_EVIDENCE,
    UNCERTAIN_THRESHOLD,
    UNDATED_RECENCY_OFFICIAL,
    UNDATED_RECENCY_OTHER,
)


@dataclass(frozen=True)
class ScoreParams:
    """The tunable constants. The defaults come from config.py."""

    min_evidence: float = MIN_EVIDENCE
    fresh_threshold: int = FRESH_THRESHOLD
    uncertain_threshold: int = UNCERTAIN_THRESHOLD
    undated_official: float = UNDATED_RECENCY_OFFICIAL
    undated_other: float = UNDATED_RECENCY_OTHER
    # Multiplies every category's half-life, for tuning them together.
    half_life_scale: float = 1.0


DEFAULT_PARAMS = ScoreParams()

# How far ahead to look for the day a verdict would change. Laws, the slowest
# category, can stay fresh for about two years, so look further than that.
RECHECK_HORIZON_DAYS = 5 * 365
RECHECK_STEP_DAYS = 7


@dataclass(frozen=True)
class SourceInput:
    authority: float
    published_date: date | None
    stance: str
    # Sources sharing a group (same owner or same story) count once per stance.
    group: str | None = None


@dataclass(frozen=True)
class ScoredSource:
    authority: float
    recency: float
    weight: float
    stance: str
    counted: bool = True


@dataclass(frozen=True)
class ClaimScore:
    score: int | None
    verdict: str
    confidence: float
    supporting_weight: float
    contradicting_weight: float
    agreement: float | None
    best_recency: float
    half_life_days: int
    sources: tuple[ScoredSource, ...]
    independent_sources: int = 0


def recency(
    published_date: date | None,
    check_date: date,
    half_life_days: float,
    authority: float,
    params: ScoreParams = DEFAULT_PARAMS,
) -> float:
    if published_date is None:
        return params.undated_official if authority == 1.0 else params.undated_other
    # A date after the check date is treated as today, never as extra-fresh.
    age_days = max((check_date - published_date).days, 0)
    return 0.5 ** (age_days / half_life_days)


def verdict_for(score: int | None, params: ScoreParams = DEFAULT_PARAMS) -> str:
    if score is None:
        return "unverified"
    if score >= params.fresh_threshold:
        return "fresh"
    if score >= params.uncertain_threshold:
        return "uncertain"
    return "stale"


def confidence_label(confidence: float) -> str:
    if confidence >= CONFIDENCE_HIGH:
        return "High"
    if confidence >= CONFIDENCE_MEDIUM:
        return "Med"
    return "Low"


def score_claim(
    sources: Sequence[SourceInput],
    category: str,
    check_date: date,
    half_life_days: int | None = None,
    params: ScoreParams = DEFAULT_PARAMS,
) -> ClaimScore:
    """Score one claim from its judged evidence."""
    base_half_life = half_life_days if half_life_days is not None else HALF_LIFE_DAYS[category]
    half_life = base_half_life * params.half_life_scale

    scored: list[ScoredSource] = []
    for source in sources:
        source_recency = recency(
            source.published_date, check_date, half_life, source.authority, params
        )
        # Irrelevant sources stay visible in the breakdown but carry no weight.
        relevant = source.stance in ("supports", "contradicts")
        weight = source.authority * source_recency if relevant else 0.0
        scored.append(ScoredSource(source.authority, source_recency, weight, source.stance))

    # Within a group, only the heaviest source for each stance counts.
    best: dict[tuple[str, str], int] = {}
    for index, (source, item) in enumerate(zip(sources, scored)):
        if source.group is None or item.weight == 0:
            continue
        key = (source.group, item.stance)
        if key not in best or item.weight > scored[best[key]].weight:
            best[key] = index
    for index, (source, item) in enumerate(zip(sources, scored)):
        if source.group is not None and item.weight > 0 and best[(source.group, item.stance)] != index:
            scored[index] = ScoredSource(item.authority, item.recency, 0.0, item.stance, counted=False)

    supporting = [item for item in scored if item.stance == "supports"]
    support_weight = sum(item.weight for item in supporting)
    contradict_weight = sum(item.weight for item in scored if item.stance == "contradicts")
    total = support_weight + contradict_weight
    best_recency = max((item.recency for item in supporting), default=0.0)
    confidence = 1 - math.exp(-total / CONFIDENCE_SCALE)

    score: int | None = None
    agreement: float | None = None
    if total >= params.min_evidence:
        agreement = support_weight / total
        score = round(100 * agreement * (0.5 + 0.5 * best_recency))

    return ClaimScore(
        score=score,
        verdict=verdict_for(score, params),
        confidence=confidence,
        supporting_weight=support_weight,
        contradicting_weight=contradict_weight,
        agreement=agreement,
        best_recency=best_recency,
        half_life_days=round(half_life),
        sources=tuple(scored),
        independent_sources=sum(1 for item in scored if item.weight > 0),
    )


def verdict_change_date(
    sources: Sequence[SourceInput],
    category: str,
    check_date: date,
    params: ScoreParams = DEFAULT_PARAMS,
    horizon_days: int = RECHECK_HORIZON_DAYS,
    half_life_days: int | None = None,
) -> date | None:
    """The first day a fresh or uncertain verdict would change if no new evidence
    appeared, as its sources age. None if it won't change within the horizon.
    """
    current = score_claim(sources, category, check_date, half_life_days, params).verdict
    if current not in ("fresh", "uncertain"):
        return None

    def changed(days: int) -> bool:
        day = check_date + timedelta(days=days)
        return score_claim(sources, category, day, half_life_days, params).verdict != current

    # Step a week at a time, then find the exact day within that week.
    for week_end in range(RECHECK_STEP_DAYS, horizon_days + RECHECK_STEP_DAYS, RECHECK_STEP_DAYS):
        week_end = min(week_end, horizon_days)
        if changed(week_end):
            for days in range(week_end - RECHECK_STEP_DAYS + 1, week_end + 1):
                if days > 0 and changed(days):
                    return check_date + timedelta(days=days)
        if week_end == horizon_days:
            break
    return None


def answer_score(
    scored_claims: Iterable[tuple[str, int]], half_lives: dict[str, int] | None = None
) -> int | None:
    """Weighted mean of (category, score) pairs. Faster-changing claims count more."""
    half_lives = half_lives or HALF_LIFE_DAYS
    weighted = 0.0
    total_weight = 0.0
    for category, score in scored_claims:
        weight = 1 / half_lives.get(category, HALF_LIFE_DAYS[category])
        weighted += weight * score
        total_weight += weight
    return round(weighted / total_weight) if total_weight else None
