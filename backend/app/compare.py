"""Contradictions across AI apps: the same question answered by several assistants.

Each app's answer is split into claims. Claims about the same fact are grouped,
searched once, and each version is judged against the same evidence, so you can
see which app is out of date.
"""

from __future__ import annotations

import asyncio
import re
from datetime import date
from difflib import SequenceMatcher
from typing import Annotated, Any

from pydantic import BaseModel, Field, StringConstraints

from app import config, llm, workspace
from app.models import AnswerText, CheckContext, Claim, ClaimResult, QuestionText
from app.pipeline.adjudicate import adjudicate_claim
from app.pipeline.extract import extract_claims
from app.pipeline.metrics import MetricsCollector
from app.pipeline.orchestrator import BUDGET_MESSAGE, PipelineError, assemble_result
from app.pipeline.retrieve import retrieve_sources

SAME_FACT = 0.75


class AppAnswer(BaseModel):
    app: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
    answer: AnswerText


class CompareRequest(BaseModel):
    question: QuestionText | None = None
    answers: list[AppAnswer] = Field(min_length=2, max_length=5)
    context: CheckContext | None = None


def _without_numbers(text: str) -> str:
    return " ".join(re.sub(r"[\d$€£₹.,%]+", " ", text.casefold()).split())


def _value(claim: Claim) -> str:
    return str(claim.number) if claim.number is not None else _without_numbers(claim.text)


def group_claims(entries: list[tuple[int, Claim]]) -> list[list[tuple[int, Claim]]]:
    """Group claims about the same fact, whatever value each app gave it."""
    groups: list[list[tuple[int, Claim]]] = []
    for entry in entries:
        key = _without_numbers(entry[1].text)
        for group in groups:
            first = group[0][1]
            if first.category == entry[1].category and SequenceMatcher(
                None, _without_numbers(first.text), key
            ).ratio() >= SAME_FACT:
                group.append(entry)
                break
        else:
            groups.append([entry])
    return groups


async def run_compare(request: CompareRequest) -> dict[str, Any]:
    settings = config.get_settings()
    if settings.missing_required():
        raise PipelineError(f"Missing settings in .env: {', '.join(settings.missing_required())}.", "not_configured")
    today = date.today()
    metrics = MetricsCollector()
    try:
        extracted = await asyncio.gather(*(
            extract_claims(item.answer, request.question, None, today, metrics) for item in request.answers
        ))
    except llm.BudgetExceededError as exc:
        raise PipelineError(BUDGET_MESSAGE, "budget_exceeded") from exc
    except llm.LLMError as exc:
        raise PipelineError(f"Could not extract claims: {exc}", "extraction_failed") from exc

    entries = [
        (index, claim)
        for index, claims in enumerate(extracted)
        for claim in claims
        if claim.kind not in ("calculation", "recommendation") and claim.time_sensitive and claim.category != "static"
    ]
    groups = group_claims(entries)
    search_slots = asyncio.Semaphore(settings.tavily_concurrency)
    llm_slots = asyncio.Semaphore(settings.llm_concurrency)

    async def judge(group: list[tuple[int, Claim]]) -> dict[str, Any]:
        retrieved = await retrieve_sources(group[0][1], search_slots, metrics, False, request.context)
        variants: dict[str, ClaimResult | None] = {}
        for _, claim in group:
            key = " ".join(claim.text.casefold().split())
            if key in variants or not retrieved.sources:
                variants.setdefault(key, None)
                continue
            try:
                async with llm_slots:
                    adjudication = await adjudicate_claim(
                        claim, retrieved.sources, today, None, metrics, request.context
                    )
                variants[key] = assemble_result(claim, retrieved.sources, adjudication, today)
            except llm.LLMError:
                variants[key] = None
        rows = []
        for index, claim in group:
            outcome = variants.get(" ".join(claim.text.casefold().split()))
            contradiction = next((e for e in (outcome.evidence if outcome else []) if e.stance == "contradicts" and e.quote), None)
            support = next((e for e in (outcome.evidence if outcome else []) if e.stance == "supports" and e.quote), None)
            evidence = contradiction or support
            rows.append({
                "app": request.answers[index].app,
                "claim": claim.text,
                "verdict": outcome.verdict if outcome else "unverified",
                "score": outcome.freshness_score if outcome else None,
                "current_value": outcome.current_value if outcome else None,
                "quote": evidence.quote if evidence else None,
                "source_url": evidence.url if evidence else None,
            })
        current = next((row["current_value"] for row in rows if row["current_value"]), None)
        return {
            "topic": group[0][1].text,
            "category": group[0][1].category,
            "conflict": len({_value(claim) for _, claim in group}) > 1,
            "current_value": current,
            "entries": rows,
        }

    clusters = await asyncio.gather(*(judge(group) for group in groups))
    clusters = sorted(clusters, key=lambda cluster: (not cluster["conflict"], cluster["topic"]))
    apps = []
    for index, item in enumerate(request.answers):
        rows = [row for cluster in clusters for row in cluster["entries"] if row["app"] == item.app]
        apps.append({
            "app": item.app,
            "answer": item.answer,
            "claims": len(rows),
            "stale": sum(row["verdict"] == "stale" for row in rows),
            "fresh": sum(row["verdict"] == "fresh" for row in rows),
            "other": sum(row["verdict"] not in ("stale", "fresh") for row in rows),
        })
    result = {
        "id": workspace.new_id(),
        "created_at": workspace.now(),
        "question": request.question,
        "clusters": clusters,
        "apps": apps,
        "conflicts": sum(cluster["conflict"] for cluster in clusters),
        "metrics": metrics.snapshot().model_dump(mode="json"),
    }
    workspace.save_comparison(result)
    return result
