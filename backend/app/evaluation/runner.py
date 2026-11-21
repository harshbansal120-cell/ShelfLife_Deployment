"""Run the pipeline over labelled answers and record what it predicted."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from app.evaluation.dataset import EvalItem
from app.evaluation.matching import match_claims
from app.evaluation.metrics import ClaimRecord, ItemRun
from app.pipeline import orchestrator


async def evaluate_item(
    item: EvalItem, use_cache: bool = True
) -> tuple[ItemRun, list[ClaimRecord]]:
    try:
        result = await orchestrator.run_check(
            item.answer,
            question=item.question,
            answer_date=item.answer_date,
            use_cache=use_cache,
        )
    except orchestrator.PipelineError as exc:
        return ItemRun(item.id, item.topic, ok=False, error=str(exc)), []

    predicted = result.claims
    matches = match_claims(
        [claim.text for claim in item.claims], [p.claim.text for p in predicted]
    )
    records = []
    for gold, (index, similarity) in zip(item.claims, matches):
        match = predicted[index] if index is not None else None
        records.append(
            ClaimRecord(
                item_id=item.id,
                topic=item.topic,
                gold_text=gold.text,
                gold=gold.gold or "",
                predicted_text=match.claim.text if match else None,
                similarity=round(similarity, 3),
                verdict=match.verdict if match else None,
                score=match.freshness_score if match else None,
                category=match.claim.category if match else None,
                check_date=result.check_date.isoformat(),
                evidence=[
                    {
                        "authority": source.authority,
                        "published_date": (
                            source.published_date.isoformat() if source.published_date else None
                        ),
                        "stance": source.stance,
                        "group": source.group,
                    }
                    for source in (match.evidence if match else [])
                ],
            )
        )

    metrics = result.metrics
    matched = {index for index, _ in matches if index is not None}
    run = ItemRun(
        item_id=item.id,
        topic=item.topic,
        ok=True,
        latency_ms=metrics.latency_ms,
        cost_usd=metrics.cost_usd,
        unpriced_calls=metrics.unpriced_calls,
        llm_calls=metrics.llm_calls,
        cache_hits=metrics.cache_hits,
        tavily_credits=metrics.tavily_credits,
        extra_predictions=len(predicted) - len(matched),
    )
    return run, records


async def evaluate(
    items: list[EvalItem],
    concurrency: int = 2,
    use_cache: bool = True,
    on_progress: Callable[[ItemRun], None] | None = None,
) -> tuple[list[ItemRun], list[ClaimRecord]]:
    slots = asyncio.Semaphore(concurrency)

    async def one(item: EvalItem) -> tuple[ItemRun, list[ClaimRecord]]:
        async with slots:
            outcome = await evaluate_item(item, use_cache)
        if on_progress:
            on_progress(outcome[0])
        return outcome

    outcomes = await asyncio.gather(*(one(item) for item in items))
    runs = [run for run, _ in outcomes]
    records = [record for _, item_records in outcomes for record in item_records]
    return runs, records
