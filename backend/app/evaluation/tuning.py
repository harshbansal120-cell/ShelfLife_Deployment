"""Re-score saved evidence with different constants, without new searches or LLM calls.

Only the code-computed score changes. The model's stances and the sources stay as
they were in the evaluation run.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from itertools import product
from typing import Any

from app.evaluation.metrics import ClaimRecord, stale_detection
from app.pipeline.score import DEFAULT_PARAMS, ScoreParams, SourceInput, score_claim

UNCHANGED_VERDICTS = (None, "not_time_sensitive", "error")


def rescore(record: ClaimRecord, params: ScoreParams) -> ClaimRecord:
    if record.verdict in UNCHANGED_VERDICTS or record.category in (None, "static"):
        return record
    sources = [
        SourceInput(
            item["authority"],
            date.fromisoformat(item["published_date"]) if item["published_date"] else None,
            item["stance"],
            item.get("group"),
        )
        for item in record.evidence
    ]
    scored = score_claim(sources, record.category, date.fromisoformat(record.check_date), params=params)
    return replace(record, verdict=scored.verdict, score=scored.score)


def evaluate_params(records: list[ClaimRecord], params: ScoreParams) -> dict[str, Any]:
    rescored = [rescore(record, params) for record in records]
    detection = stale_detection(rescored, {"stale"})
    timely = [r for r in rescored if r.gold in ("stale", "fresh") and r.verdict is not None]
    fresh = [r for r in rescored if r.gold == "fresh"]
    return {
        "params": params,
        **detection,
        "false_alarm_rate": detection["fp"] / len(fresh) if fresh else None,
        "unverified_rate": (
            sum(r.verdict in ("unverified", "error") for r in timely) / len(timely)
            if timely
            else None
        ),
    }


DEFAULT_GRID = {
    "half_life_scale": (0.5, 0.75, 1.0, 1.5, 2.0),
    "uncertain_threshold": (30, 35, 40, 45, 50),
    "min_evidence": (0.1, 0.15, 0.2, 0.3),
}


def sweep(
    records: list[ClaimRecord], grid: dict[str, tuple] = DEFAULT_GRID
) -> list[dict[str, Any]]:
    """Every combination in the grid, best F1 first, then fewest unverified claims."""
    names = list(grid)
    rows = [
        evaluate_params(records, replace(DEFAULT_PARAMS, **dict(zip(names, values))))
        for values in product(*(grid[name] for name in names))
    ]
    return sorted(
        rows,
        key=lambda row: (-(row["f1"] or 0), row["unverified_rate"] or 0),
    )
