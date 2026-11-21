"""Claims that are worked out from other claims: calculations and recommendations.

Calculations are redone in code with the current values of their inputs. A
recommendation is re-judged by the strong model only when something it relies on
has changed, and its revised wording may only use numbers from the facts.
"""

from __future__ import annotations

import ast
import operator
import re
from collections.abc import Callable

from pydantic import BaseModel

from app import config, llm
from app.models import (
    DERIVED_KINDS,
    ChangeInfo,
    Claim,
    ClaimResult,
    DecisionInfo,
    RecalcInput,
    Recalculation,
)
from app.pipeline.metrics import MetricsCollector
from app.policies import CATEGORY_LABELS, FreshnessPolicy
from app.prompts import load_prompt, neutralise_tag

_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
_PLACEHOLDER = re.compile(r"\{(c\d+)\}")
_OPERATORS: dict[type, Callable] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
CHANGED_TOLERANCE = 0.005


def parse_number(text: str | None) -> float | None:
    """The first number in a piece of text, such as 28 in "$28 per seat"."""
    if not text:
        return None
    match = _NUMBER.search(text)
    return float(match.group().replace(",", "")) if match else None


def evaluate(formula: str, values: dict[str, float]) -> float | None:
    """Safely evaluate arithmetic over claim values. Anything else gives None."""

    def value_of(match: re.Match) -> str:
        if match.group(1) not in values:
            raise KeyError(match.group(1))
        return repr(values[match.group(1)])

    try:
        expression = _PLACEHOLDER.sub(value_of, formula)
        tree = ast.parse(expression, mode="eval")
        return _eval(tree.body)
    except (KeyError, SyntaxError, ValueError, ZeroDivisionError, TypeError):
        return None


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
        return _OPERATORS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        value = _eval(node.operand)
        return -value if isinstance(node.op, ast.USub) else value
    raise ValueError("unsupported expression")


def format_like(template: str, value: float) -> str:
    """Write a number the way the answer wrote the original, such as "$280" or "40%"."""
    match = _NUMBER.search(template)
    commas = bool(match and "," in match.group())
    digits = f"{abs(value):,.2f}" if commas else f"{abs(value):.2f}"
    digits = digits.rstrip("0").rstrip(".")
    sign = "-" if value < 0 else ""
    if not match:
        return sign + digits
    before = template[match.start() - 1] if match.start() > 0 else ""
    after = template[match.end()] if match.end() < len(template) else ""
    prefix = before if before in "$€£₹¥" else ""
    suffix = "%" if after == "%" else ""
    return f"{sign}{prefix}{digits}{suffix}"


def _changed(old: float, new: float) -> bool:
    return abs(new - old) > CHANGED_TOLERANCE * max(1.0, abs(old))


def _order(derived: list[Claim]) -> list[Claim]:
    """Calculations before what depends on them, then recommendations."""
    ids = {claim.id for claim in derived}
    ordered: list[Claim] = []
    placed: set[str] = set()
    pending = sorted(derived, key=lambda claim: claim.kind != "calculation")
    for _ in range(len(pending) + 1):
        for claim in list(pending):
            if all(dep in placed or dep not in ids for dep in claim.depends_on):
                ordered.append(claim)
                placed.add(claim.id)
                pending.remove(claim)
    return ordered + pending  # cycles keep their original order


def current_number(result: ClaimResult) -> float | None:
    """A claim's value now: recomputed for calculations, from sources for stale facts."""
    if result.recalculation and result.recalculation.recomputed is not None:
        return result.recalculation.recomputed
    if result.verdict == "stale" and result.current_value:
        return parse_number(result.current_value)
    return result.claim.number


def recalculate(claim: Claim, answer: str, results: dict[str, ClaimResult]) -> ClaimResult:
    inputs = [results[dep] for dep in claim.depends_on if dep in results]
    stated_values = {r.claim.id: r.claim.number for r in inputs if r.claim.number is not None}
    current_values = {r.claim.id: v for r in inputs if (v := current_number(r)) is not None}
    stated = claim.number if claim.number is not None else evaluate(claim.formula or "", stated_values)
    recomputed = evaluate(claim.formula or "", current_values) if claim.formula else None
    recalc = Recalculation(
        formula=claim.formula or "",
        stated=stated,
        recomputed=recomputed,
        inputs=[
            RecalcInput(claim_id=r.claim.id, stated=r.claim.number, current=current_number(r))
            for r in inputs
        ],
    )
    template = answer[claim.span[0] : claim.span[1]] if claim.span else claim.text
    verdicts = {r.verdict for r in inputs}

    if recomputed is None or stated is None:
        return _derived(claim, "unverified", "This figure can't be recalculated: an input has no number.", recalc)
    if "stale" in verdicts and _changed(stated, recomputed):
        new_value = format_like(template, recomputed)
        return _derived(
            claim,
            "stale",
            f"Recalculated with current inputs: {format_like(template, stated)} is now {new_value}.",
            recalc,
            current_value=new_value,
            change=ChangeInfo(
                change_type="value_changed",
                old_value=format_like(template, stated),
                new_value=new_value,
                as_of=None,
                source_url=None,
            ),
        )
    if verdicts & {"unverified", "error"}:
        return _derived(claim, "unverified", "Some inputs couldn't be verified, so this figure can't be confirmed.", recalc)
    if verdicts & {"uncertain"}:
        return _derived(claim, "uncertain", "Some inputs are uncertain, so this figure may be out of date.", recalc)
    own_arithmetic = evaluate(claim.formula or "", stated_values)
    note = ""
    if own_arithmetic is not None and claim.number is not None and _changed(claim.number, own_arithmetic):
        note = f" Note: the answer's own arithmetic gives {format_like(template, own_arithmetic)}."
    return _derived(claim, "fresh", f"Still correct with the current inputs.{note}", recalc)


class DecisionOutput(BaseModel):
    holds: str
    revised: str | None = None
    reason: str = ""


def stale_dependencies(
    claim_id: str,
    results: dict[str, ClaimResult],
    seen: set[str] | None = None,
    depends_on: list[str] | None = None,
) -> list[str]:
    """Stale claims this one relies on, directly or through other claims."""
    seen = seen if seen is not None else set()
    found: list[str] = []
    if depends_on is None:
        depends_on = results[claim_id].claim.depends_on if claim_id in results else []
    for dep in depends_on:
        if dep in seen or dep not in results:
            continue
        seen.add(dep)
        if results[dep].verdict == "stale":
            found.append(dep)
        found += stale_dependencies(dep, results, seen)
    return found


async def review_recommendation(
    claim: Claim, results: dict[str, ClaimResult], metrics: MetricsCollector
) -> ClaimResult:
    deps = [results[dep] for dep in claim.depends_on if dep in results]
    stale = stale_dependencies(claim.id, results, depends_on=claim.depends_on)
    if not stale:
        if any(r.verdict in ("unverified", "error", "uncertain") for r in deps):
            return _derived(claim, "uncertain", "Some facts it relies on couldn't be confirmed.")
        if not deps:
            return _derived(claim, "unverified", "The answer doesn't say what this relies on.")
        return _derived(claim, "fresh", "Every fact it relies on is still current.")

    lines = []
    allowed_numbers = set(_NUMBER.findall(claim.text))
    for dep in deps:
        now = dep.current_value or "unchanged"
        lines.append(f"- {dep.claim.text} | now: {now} | verdict: {dep.verdict}")
        allowed_numbers |= set(_NUMBER.findall(dep.claim.text)) | set(_NUMBER.findall(now))
    settings = config.get_settings()
    messages = [
        {"role": "system", "content": load_prompt("decision")},
        {
            "role": "user",
            "content": (
                f"<recommendation>\n{neutralise_tag(claim.text, 'recommendation')}\n</recommendation>\n\n"
                f"<facts>\n{neutralise_tag(chr(10).join(lines), 'facts')}\n</facts>"
            ),
        },
    ]
    try:
        response = await metrics.chat(
            "decision", messages, settings.model_strong, settings.fallbacks_strong_list,
            json_schema=DecisionOutput,
        )
    except llm.LLMError:
        return _derived(
            claim, "uncertain", "Facts it relies on have changed, and it couldn't be re-judged.",
            affected_by=stale,
        )
    output: DecisionOutput = response.parsed
    holds = output.holds if output.holds in ("yes", "no", "unclear") else "unclear"
    revised = (output.revised or "").strip() or None
    # The revised wording may only use numbers that appear in the facts.
    if revised and not set(_NUMBER.findall(revised)) <= allowed_numbers:
        revised = None
    verdict = {"yes": "fresh", "no": "stale", "unclear": "uncertain"}[holds]
    decision = DecisionInfo(
        holds=holds, reason=output.reason.strip(), revised=revised if holds == "no" else None,
        judged_by=response.served_by,
    )
    return _derived(
        claim,
        verdict,
        output.reason.strip() or "Re-judged with the current facts.",
        decision=decision,
        current_value=decision.revised,
        affected_by=stale,
    )


def _derived(
    claim: Claim,
    verdict: str,
    explanation: str,
    recalculation: Recalculation | None = None,
    *,
    current_value: str | None = None,
    change: ChangeInfo | None = None,
    decision: DecisionInfo | None = None,
    affected_by: list[str] | None = None,
) -> ClaimResult:
    return ClaimResult(
        claim=claim,
        verdict=verdict,
        freshness_score=None,
        confidence=0.0,
        current_value=current_value,
        explanation=explanation,
        evidence=[],
        recalculation=recalculation,
        decision=decision,
        change=change,
        affected_by=affected_by or [],
    )


async def resolve_derived(
    claims: list[Claim],
    answer: str,
    results: dict[str, ClaimResult],
    metrics: MetricsCollector,
    on_result: Callable | None = None,
) -> None:
    """Work out calculations and recommendations once the facts are checked."""
    derived = [claim for claim in claims if claim.kind in DERIVED_KINDS]
    for claim in _order(derived):
        if claim.kind == "calculation":
            result = recalculate(claim, answer, results)
        else:
            result = await review_recommendation(claim, results, metrics)
        results[claim.id] = result
        if on_result:
            await on_result(result)
    # Every claim learns which stale claims it rests on.
    for claim_id, result in list(results.items()):
        affected = stale_dependencies(claim_id, results)
        if affected != result.affected_by:
            results[claim_id] = result.model_copy(update={"affected_by": affected})


def guard(results: list[ClaimResult], policy: FreshnessPolicy | None = None) -> tuple[str, str]:
    """Advise an app whether to show the answer, warn, or hold it back."""
    checked = [r for r in results if r.verdict != "not_time_sensitive"]
    stale = [r for r in checked if r.verdict == "stale"]
    ratio = policy.withhold_ratio if policy else 0.5
    if any(r.claim.kind == "recommendation" for r in stale):
        return "withhold", "A recommendation in this answer relies on facts that have changed."
    serious = [r for r in stale if policy and r.claim.category in policy.withhold_categories]
    if serious:
        label = CATEGORY_LABELS.get(serious[0].claim.category, serious[0].claim.category)
        return "withhold", f"The {policy.name} policy holds back answers with a stale {label} claim."
    if stale and len(stale) >= ratio * len(checked):
        share = "half" if ratio == 0.5 else f"{round(ratio * 100)}%"
        return "withhold", f"At least {share} of the checked claims are out of date."
    if stale:
        return "show_with_warning", f"{len(stale)} claim(s) are out of date; show the corrected answer."
    if any(r.verdict in ("uncertain", "unverified", "error") for r in checked):
        return "show_with_warning", "Some claims couldn't be confirmed against current sources."
    return "show", "Every time-sensitive claim matches current sources."
