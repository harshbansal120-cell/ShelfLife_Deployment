"""Pair each gold claim with the extracted claim that says the same thing."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

MATCH_THRESHOLD = 0.5
# Two claims about the same entity with different numbers ("costs $10" and
# "has 10 million users") are probably different claims.
NUMBER_MISMATCH_PENALTY = 0.6


def _normalise(text: str) -> str:
    text = re.sub(r"(?<=\d),(?=\d)", "", text.casefold())
    return " ".join(re.sub(r"[^\w\s$%.]", " ", text).replace(". ", " ").split()).rstrip(".")


def _numbers(text: str) -> set[str]:
    return {match.replace(",", "") for match in re.findall(r"\d[\d,]*(?:\.\d+)?", text)}


def similarity(left: str, right: str) -> float:
    a, b = _normalise(left), _normalise(right)
    if not a or not b:
        return 0.0
    ratio = SequenceMatcher(None, a, b).ratio()
    words_a, words_b = set(a.split()), set(b.split())
    overlap = len(words_a & words_b) / len(words_a | words_b)
    score = max(ratio, overlap)
    numbers_a, numbers_b = _numbers(left), _numbers(right)
    if numbers_a and numbers_b and not numbers_a & numbers_b:
        score *= NUMBER_MISMATCH_PENALTY
    return score


def match_claims(
    gold: list[str], predicted: list[str], threshold: float = MATCH_THRESHOLD
) -> list[tuple[int | None, float]]:
    """For each gold claim, the index of its predicted match (or None) and the similarity.

    Pairs are taken best first, and each predicted claim is used at most once.
    """
    candidates = sorted(
        (
            (similarity(g, p), gi, pi)
            for gi, g in enumerate(gold)
            for pi, p in enumerate(predicted)
        ),
        reverse=True,
    )
    matches: list[tuple[int | None, float]] = [(None, 0.0)] * len(gold)
    used_gold: set[int] = set()
    used_predicted: set[int] = set()
    for score, gi, pi in candidates:
        if score < threshold:
            break
        if gi in used_gold or pi in used_predicted:
            continue
        matches[gi] = (pi, score)
        used_gold.add(gi)
        used_predicted.add(pi)
    return matches
