"""Details that ride on a stale value.

Answers often state a value and then describe it in the same breath: "the latest
release is version 3.13, launched on October 7, 2024". The extractor rightly splits
that into "the latest release is 3.13" (time-sensitive) and "3.13 was launched on
October 7, 2024" (true forever). But once the first claim is corrected to 3.15, the
date written beside it describes 3.15, and is wrong. Correcting the value alone
would leave the answer internally inconsistent.

This stage finds such coupled details, restates each one about the current value
("3.15 was launched on October 7, 2024"), and checks the restatement against live
sources like any other claim. The rewrite then corrects the value and its details
together, with the details' own sources.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import BaseModel

from app import config, llm
from app.models import DERIVED_KINDS, Claim, ClaimResult
from app.passport import passport_id
from app.pipeline.metrics import MetricsCollector
from app.prompts import load_prompt, neutralise_tag

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")

ClaimChecker = Callable[[Claim], Awaitable[ClaimResult]]


@dataclass(frozen=True)
class Coupling:
    detail: Claim
    anchor: ClaimResult


class RetargetItem(BaseModel):
    id: str
    # False when the detail doesn't describe the anchor's value, so it needs no re-check.
    transfers: bool = True
    text: str = ""
    search_queries: list[str] = []


class RetargetOutput(BaseModel):
    items: list[RetargetItem]


def _overlap(left: tuple[int, int] | None, right: tuple[int, int] | None) -> bool:
    return bool(left and right) and left[0] < right[1] and right[0] < left[1]


def is_anchor(result: ClaimResult) -> bool:
    """A stale fact whose new value is known: something the answer's details may hang on."""
    return (
        result.verdict == "stale"
        and bool(result.current_value)
        and result.claim.kind not in DERIVED_KINDS
    )


def find_couplings(claims: list[Claim], results: dict[str, ClaimResult]) -> list[Coupling]:
    """Details that describe a stale value: they rely on it, or share its passage."""
    anchors = [results[c.id] for c in claims if c.id in results and is_anchor(results[c.id])]
    couplings = []
    for claim in claims:
        current = results.get(claim.id)
        if claim.kind in DERIVED_KINDS or current is None or current.verdict == "stale":
            continue
        anchor = next(
            (
                item
                for item in anchors
                if item.claim.id != claim.id
                # A detail about a past time still describes that time, not today's value.
                and not (claim.historical and not item.claim.historical)
                and (item.claim.id in claim.depends_on or _overlap(item.claim.span, claim.span))
            ),
            None,
        )
        if anchor is not None:
            couplings.append(Coupling(claim, anchor))
    return couplings


def _value_tokens(text: str | None) -> list[str]:
    return _NUMBER.findall(text or "")


def substitute(text: str, anchor: ClaimResult) -> str | None:
    """Swap the anchor's old number for its new one, when each has exactly one."""
    old_text = anchor.change.old_value if anchor.change and anchor.change.old_value else anchor.claim.text
    old = _value_tokens(old_text)
    new = _value_tokens(anchor.current_value)
    if len(set(old)) != 1 or len(set(new)) != 1 or old[0] == new[0]:
        return None
    pattern = rf"(?<![\d.]){re.escape(old[0])}(?![\d]|\.\d)"
    if not re.search(pattern, text):
        return None
    return re.sub(pattern, new[0], text)


def build_messages(couplings: list[Coupling], answer: str) -> list[dict]:
    parts = [f"<answer>\n{neutralise_tag(answer, 'answer')}\n</answer>"]
    for coupling in couplings:
        anchor = coupling.anchor
        old = anchor.change.old_value if anchor.change and anchor.change.old_value else ""
        fields = "\n".join([
            f"value claim: {anchor.claim.text}",
            f"value as stated: {old or anchor.claim.text}",
            f"current value: {anchor.current_value}",
            f"detail claim: {coupling.detail.text}",
        ])
        body = neutralise_tag(neutralise_tag(fields, "item"), "answer")
        parts.append(f'<item id="{coupling.detail.id}">\n{body}\n</item>')
    return [
        {"role": "system", "content": load_prompt("retarget")},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def _valid_restatement(text: str, anchor: ClaimResult) -> bool:
    """The restatement must name the current value's numbers, if it has any."""
    if not text.strip():
        return False
    numbers = set(_value_tokens(anchor.current_value))
    return not numbers or bool(numbers & set(_value_tokens(text)))


async def restate(
    couplings: list[Coupling], answer: str, metrics: MetricsCollector
) -> dict[str, Claim]:
    """Each detail, restated about the current value. Details that don't transfer are left out."""
    if not couplings:
        return {}
    settings = config.get_settings()
    items: dict[str, RetargetItem] = {}
    try:
        response = await metrics.chat(
            "retarget",
            build_messages(couplings, answer),
            settings.model_fast,
            settings.fallbacks_fast_list,
            json_schema=RetargetOutput,
        )
        items = {item.id: item for item in response.parsed.items}
    except llm.LLMError:
        # Without the model, fall back to swapping the number in code.
        items = {}

    restated: dict[str, Claim] = {}
    for coupling in couplings:
        detail, anchor = coupling.detail, coupling.anchor
        item = items.get(detail.id)
        if item is not None and not item.transfers:
            continue
        text = item.text.strip() if item and _valid_restatement(item.text, anchor) else None
        queries = [q.strip() for q in item.search_queries if q.strip()] if item and text else []
        if text is None:
            text = substitute(detail.text, anchor)
            if text is None:
                continue
            queries = [q for q in (substitute(q, anchor) for q in detail.search_queries) if q]
        category = detail.category if detail.category != "static" else anchor.claim.category
        restated[detail.id] = detail.model_copy(update={
            "text": text,
            "category": category,
            "time_sensitive": True,
            "search_queries": (queries or [text])[: config.MAX_QUERIES_PER_CLAIM],
            "entities": list(dict.fromkeys([*detail.entities, *anchor.claim.entities])),
            "official_domains": detail.official_domains or anchor.claim.official_domains,
            "passport_id": passport_id(text),
        })
    return restated


def coupled_result(detail: Claim, anchor: ClaimResult, checked: ClaimResult) -> ClaimResult:
    """The detail's verdict in the answer, from the check of its restatement."""
    new_value = anchor.current_value
    if checked.verdict in ("fresh", "uncertain"):
        verdict = checked.verdict
        explanation = f"Once corrected, this detail describes {new_value}, and it still holds. {checked.explanation}"
    elif checked.verdict == "stale":
        verdict = "stale"
        explanation = (
            f"This detail describes the value now given as {new_value}; for it, sources say "
            f"{checked.current_value}. {checked.explanation}"
        )
    else:
        verdict = "unverified"
        explanation = (
            f"This detail was written about the old value. It couldn't be confirmed for "
            f"{new_value}, so it is flagged. {checked.explanation}"
        )
    claim = detail.model_copy(update={
        "category": checked.claim.category,
        "time_sensitive": True,
        "depends_on": list(dict.fromkeys([*detail.depends_on, anchor.claim.id])),
        "passport_id": checked.claim.passport_id,
    })
    return checked.model_copy(update={
        "claim": claim,
        "verdict": verdict,
        "explanation": explanation.strip(),
        "coupled_to": anchor.claim.id,
        "checked_as": checked.claim.text,
        "affected_by": [anchor.claim.id],
        "current_value": checked.current_value if verdict == "stale" else None,
        "change": checked.change if verdict == "stale" else None,
    })


async def check_coupled_details(
    claims: list[Claim],
    results: dict[str, ClaimResult],
    answer: str,
    metrics: MetricsCollector,
    check: ClaimChecker,
) -> list[ClaimResult]:
    """Re-check every detail of a stale value for the current value."""
    couplings = find_couplings(claims, results)
    restated = await restate(couplings, answer, metrics)
    todo = [coupling for coupling in couplings if coupling.detail.id in restated]
    checked = await asyncio.gather(*(check(restated[c.detail.id]) for c in todo))
    return [coupled_result(c.detail, c.anchor, result) for c, result in zip(todo, checked)]
