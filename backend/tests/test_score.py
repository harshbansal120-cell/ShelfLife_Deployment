from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.pipeline.score import (
    ScoreParams,
    SourceInput,
    answer_score,
    confidence_label,
    recency,
    score_claim,
    verdict_for,
)

CHECK_DATE = date(2026, 1, 1)
OFFICIAL = 1.0
BLOG = 0.4
FORUM = 0.2


def days_ago(days: int) -> date:
    return CHECK_DATE - timedelta(days=days)


def source(authority: float, age_days: int | None, stance: str) -> SourceInput:
    published = None if age_days is None else days_ago(age_days)
    return SourceInput(authority, published, stance)


@pytest.mark.parametrize(
    ("sources", "category", "verdict", "low", "high"),
    [
        pytest.param([source(OFFICIAL, 1, "supports")], "pricing", "fresh", 90, 100, id="recent-official-support"),
        pytest.param(
            [source(OFFICIAL, 2, "contradicts"), source(BLOG, 400, "supports")],
            "pricing", "stale", 0, 39, id="recent-official-contradiction-beats-old-blog",
        ),
        pytest.param([source(OFFICIAL, 180, "supports")], "pricing", "uncertain", 40, 69, id="old-support-only"),
        pytest.param([source(OFFICIAL, 1, "contradicts")], "pricing", "stale", 0, 0, id="contradiction-only"),
        pytest.param([source(OFFICIAL, None, "supports")], "pricing", "fresh", 85, 85, id="undated-official"),
        pytest.param(
            [source(BLOG, 1, "supports"), source(BLOG, 1, "contradicts")],
            "pricing", "uncertain", 40, 69, id="equal-sources-disagree",
        ),
    ],
)
def test_scored_claims(sources, category, verdict, low, high):
    result = score_claim(sources, category, CHECK_DATE)

    assert result.verdict == verdict
    assert low <= result.score <= high


@pytest.mark.parametrize(
    "sources",
    [
        pytest.param([], id="no-evidence"),
        pytest.param([source(OFFICIAL, 1, "irrelevant")], id="only-irrelevant"),
        pytest.param([source(BLOG, None, "supports")], id="one-undated-blog-is-too-weak"),
        pytest.param([source(FORUM, 300, "supports")], id="one-old-forum-post-is-too-weak"),
    ],
)
def test_too_little_evidence_is_unverified(sources):
    result = score_claim(sources, "pricing", CHECK_DATE)

    assert result.score is None
    assert result.verdict == "unverified"
    assert result.agreement is None


def test_irrelevant_sources_carry_no_weight_but_stay_in_the_breakdown():
    result = score_claim(
        [source(OFFICIAL, 1, "supports"), source(OFFICIAL, 1, "irrelevant")], "pricing", CHECK_DATE
    )

    assert len(result.sources) == 2
    assert result.sources[1].weight == 0
    assert result.sources[1].recency > 0
    assert result.contradicting_weight == 0
    assert result.agreement == 1


def test_longer_half_life_raises_the_score_for_the_same_age():
    sources = [source(OFFICIAL, 100, "supports")]

    fast = score_claim(sources, "pricing", CHECK_DATE)
    slow = score_claim(sources, "law_regulation", CHECK_DATE)

    assert slow.score > fast.score


def test_tuning_parameters_change_the_outcome():
    sources = [source(OFFICIAL, 180, "supports")]

    default = score_claim(sources, "pricing", CHECK_DATE)
    longer = score_claim(sources, "pricing", CHECK_DATE, params=ScoreParams(half_life_scale=2))
    stricter = score_claim(sources, "pricing", CHECK_DATE, params=ScoreParams(min_evidence=0.5))

    assert longer.score > default.score
    assert longer.half_life_days == 180
    assert stricter.verdict == "unverified"


def test_verdict_bands_follow_the_parameters():
    params = ScoreParams(fresh_threshold=80, uncertain_threshold=50)

    assert [verdict_for(score, params) for score in (80, 79, 50, 49)] == [
        "fresh",
        "uncertain",
        "uncertain",
        "stale",
    ]


def test_confidence_grows_with_evidence():
    one = score_claim([source(OFFICIAL, 1, "supports")], "pricing", CHECK_DATE)
    three = score_claim([source(OFFICIAL, 1, "supports")] * 3, "pricing", CHECK_DATE)

    assert 0 < one.confidence < three.confidence < 1


@pytest.mark.parametrize(
    ("age_days", "expected"),
    [(0, 1.0), (90, 0.5), (180, 0.25), (-30, 1.0)],
)
def test_recency_halves_each_half_life_and_ignores_future_dates(age_days, expected):
    assert recency(days_ago(age_days), CHECK_DATE, 90, BLOG) == pytest.approx(expected)


@pytest.mark.parametrize(("authority", "expected"), [(OFFICIAL, 0.7), (0.8, 0.35), (BLOG, 0.35)])
def test_recency_without_a_date(authority, expected):
    assert recency(None, CHECK_DATE, 90, authority) == expected


@pytest.mark.parametrize(
    ("score", "verdict"),
    [(100, "fresh"), (70, "fresh"), (69, "uncertain"), (40, "uncertain"), (39, "stale"), (0, "stale"), (None, "unverified")],
)
def test_verdict_bands(score, verdict):
    assert verdict_for(score) == verdict


@pytest.mark.parametrize(
    ("confidence", "label"),
    [(0.39, "Low"), (0.4, "Med"), (0.69, "Med"), (0.7, "High")],
)
def test_confidence_labels(confidence, label):
    assert confidence_label(confidence) == label


def test_answer_score_weights_fast_changing_claims_more():
    # Pricing (90 days) counts about six times as much as law (540 days).
    assert answer_score([("pricing", 0), ("law_regulation", 100)]) == 14


def test_answer_score_with_nothing_scored():
    assert answer_score([]) is None
