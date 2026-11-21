"""Turn per-claim results into the numbers in eval/results.md.

The positive class is "stale". A gold claim the pipeline didn't extract counts as
predicted "not stale", so missed stale claims lower recall.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

TIME_SENSITIVE_GOLD = ("stale", "fresh")
NOT_EXTRACTED = "not_extracted"


@dataclass
class ClaimRecord:
    item_id: str
    topic: str | None
    gold_text: str
    gold: str
    predicted_text: str | None
    similarity: float
    verdict: str | None
    score: int | None
    category: str | None
    check_date: str
    # Authority, date and stance per source, so tuning can re-score offline.
    evidence: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ItemRun:
    item_id: str
    topic: str | None
    ok: bool
    error: str | None = None
    latency_ms: int = 0
    cost_usd: float = 0.0
    unpriced_calls: int = 0
    llm_calls: int = 0
    cache_hits: int = 0
    tavily_credits: int = 0
    extra_predictions: int = 0


def _ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def stale_detection(records: list[ClaimRecord], positive: set[str]) -> dict[str, Any]:
    """Precision, recall and F1 for spotting stale claims among stale and fresh ones."""
    counts = Counter()
    for record in records:
        if record.gold not in TIME_SENSITIVE_GOLD:
            continue
        predicted = record.verdict in positive
        actual = record.gold == "stale"
        counts[("tp" if actual else "fp") if predicted else ("fn" if actual else "tn")] += 1
    precision = _ratio(counts["tp"], counts["tp"] + counts["fp"])
    recall = _ratio(counts["tp"], counts["tp"] + counts["fn"])
    f1 = None
    if precision is not None and recall is not None and precision + recall:
        f1 = 2 * precision * recall / (precision + recall)
    return {
        "tp": counts["tp"],
        "fp": counts["fp"],
        "fn": counts["fn"],
        "tn": counts["tn"],
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def summarise(records: list[ClaimRecord], runs: list[ItemRun]) -> dict[str, Any]:
    ok_items = {run.item_id for run in runs if run.ok}
    records = [record for record in records if record.item_id in ok_items]
    ok_runs = [run for run in runs if run.ok]

    matched = [record for record in records if record.verdict is not None]
    fresh = [record for record in records if record.gold == "fresh"]
    timely_matched = [record for record in matched if record.gold in TIME_SENSITIVE_GOLD]
    static_matched = [record for record in matched if record.gold == "static"]
    strict = stale_detection(records, {"stale"})

    confusion: dict[str, Counter] = defaultdict(Counter)
    for record in records:
        confusion[record.gold][record.verdict or NOT_EXTRACTED] += 1

    by_topic: dict[str, dict[str, Any]] = {}
    for topic in sorted({record.topic or "untagged" for record in records}):
        topic_records = [r for r in records if (r.topic or "untagged") == topic]
        detection = stale_detection(topic_records, {"stale"})
        by_topic[topic] = {
            "claims": len(topic_records),
            "extraction_recall": _ratio(
                sum(r.verdict is not None for r in topic_records), len(topic_records)
            ),
            "precision": detection["precision"],
            "recall": detection["recall"],
            "f1": detection["f1"],
        }

    return {
        "answers": len(ok_runs),
        "failed_answers": len(runs) - len(ok_runs),
        "gold_claims": len(records),
        "gold_counts": dict(Counter(record.gold for record in records)),
        "extraction_recall": _ratio(len(matched), len(records)),
        "extra_predictions": sum(run.extra_predictions for run in ok_runs),
        "stale_strict": strict,
        "stale_lenient": stale_detection(records, {"stale", "uncertain"}),
        "false_alarm_rate": _ratio(strict["fp"], len(fresh)),
        "unverified_rate": _ratio(
            sum(r.verdict in ("unverified", "error") for r in timely_matched),
            len(timely_matched),
        ),
        "static_handled": _ratio(
            sum(r.verdict == "not_time_sensitive" for r in static_matched),
            len(static_matched),
        ),
        "confusion": {gold: dict(counts) for gold, counts in confusion.items()},
        "by_topic": by_topic,
        "avg_latency_ms": _ratio(sum(r.latency_ms for r in ok_runs), len(ok_runs)),
        "avg_cost_usd": _ratio(sum(r.cost_usd for r in ok_runs), len(ok_runs)),
        "unpriced_calls": sum(r.unpriced_calls for r in ok_runs),
        "avg_tavily_credits": _ratio(sum(r.tavily_credits for r in ok_runs), len(ok_runs)),
        "avg_llm_calls": _ratio(sum(r.llm_calls for r in ok_runs), len(ok_runs)),
    }


def cache_hit_rate(runs: list[ItemRun]) -> float | None:
    ok_runs = [run for run in runs if run.ok]
    return _ratio(sum(r.cache_hits for r in ok_runs), sum(r.llm_calls for r in ok_runs))
