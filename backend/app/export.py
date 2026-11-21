"""Render a finished check as a Markdown report."""

from __future__ import annotations

import re

from app.models import CheckResult, ClaimResult
from app.pipeline.score import confidence_label
from app.search import domain_of

VERDICT_LABELS = {
    "fresh": "Fresh",
    "uncertain": "Uncertain",
    "stale": "Stale",
    "unverified": "Unverified",
    "error": "Couldn't check",
    "not_time_sensitive": "Doesn't change",
}


KIND_LABELS = {
    "fact": "fact",
    "assumption": "hidden assumption",
    "calculation": "calculation",
    "recommendation": "recommendation",
    "api_usage": "code",
    "availability": "availability",
}

CHANGE_LABELS = {
    "deprecated": "deprecated",
    "value_changed": "value changed",
    "superseded": "replaced by something newer",
    "discontinued": "discontinued",
    "renamed": "renamed",
    "unclear": "changed",
}


def text(value: str) -> str:
    """Escape web or model text so it can't add Markdown structure or HTML."""
    value = " ".join(value.split())
    value = value.replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"([\\`*_\[\]|#])", r"\\\1", value)


def link(label: str, url: str) -> str:
    if not url.startswith(("https://", "http://")):
        return text(label)
    safe_url = url.replace(" ", "%20").replace("(", "%28").replace(")", "%29")
    return f"[{text(label)}]({safe_url})"


def _claim_section(item: ClaimResult) -> list[str]:
    score = "" if item.freshness_score is None else f", score {item.freshness_score}/100"
    confidence = (
        f", {confidence_label(item.confidence).lower()} confidence"
        if item.freshness_score is not None
        else ""
    )
    kind = "" if item.claim.kind == "fact" else f" ({KIND_LABELS[item.claim.kind]})"
    lines = [
        f"### {item.claim.id}{kind}: {text(item.claim.text)}",
        "",
        f"- Verdict: {VERDICT_LABELS[item.verdict]}{score}{confidence}",
    ]
    if item.recalculation and item.recalculation.recomputed is not None:
        lines.append(
            f"- Recalculated: `{item.recalculation.formula}` gives {item.recalculation.recomputed:g} "
            f"(the answer said {item.recalculation.stated:g})"
            if item.recalculation.stated is not None
            else f"- Recalculated: {item.recalculation.recomputed:g}"
        )
    if item.decision:
        lines.append(f"- Still holds? {item.decision.holds} (model's judgement): {text(item.decision.reason)}")
        if item.decision.revised:
            lines.append(f"- Revised: {text(item.decision.revised)}")
    if item.affected_by:
        lines.append(f"- Relies on out-of-date claims: {', '.join(item.affected_by)}")
    if item.context_note:
        lines.append(f"- For your context: {text(item.context_note)}")
    if item.change:
        new = text(item.change.new_value)
        values = f"{text(item.change.old_value)} → {new}" if item.change.old_value else f"now {new}"
        as_of = f" (as of {item.change.as_of.isoformat()})" if item.change.as_of else ""
        lines.append(f"- What changed: {CHANGE_LABELS[item.change.change_type]}, {values}{as_of}")
    elif item.current_value:
        lines.append(f"- Sources now say: {text(item.current_value)}")
    if item.recheck_by:
        lines.append(f"- Re-check by: {item.recheck_by.isoformat()}")
    lines.append(f"- Why: {text(item.explanation)}")
    relevant = [source for source in item.evidence if source.stance != "irrelevant"]
    if relevant:
        lines.append("- Evidence:")
        for source in relevant:
            published = source.published_date.isoformat() if source.published_date else "no date"
            quote = f': "{text(source.quote)}"' if source.quote else ""
            lines.append(
                f"  - {source.stance.capitalize()}, {link(source.domain or domain_of(source.url), source.url)} "
                f"({published}, authority {source.authority:.2f}, weight {source.weight:.2f}){quote}"
            )
    if item.llm and item.llm.served_by:
        via = " (fallback)" if item.llm.is_fallback else ""
        cached = ", from Bifrost cache" if item.llm.cache_hit else ""
        lines.append(f"- Judged by: `{item.llm.served_by}`{via}{cached}")
    return lines + [""]


def to_markdown(result: CheckResult) -> str:
    counts = ", ".join(
        f"{count} {VERDICT_LABELS[verdict].lower()}"
        for verdict, count in sorted(result.verdict_counts.items())
    )
    score = "n/a" if result.answer_score is None else f"{result.answer_score}/100"
    lines = [
        "# ShelfLife freshness report",
        "",
        f"Checked on {result.check_date.isoformat()}. Answer freshness: {score}. "
        f"Claims: {counts or 'none found'}."
        + (f" Re-check this answer by {result.recheck_by.isoformat()}." if result.recheck_by else ""),
        "",
        "Scores are calculated in code from each source's authority and age, not by a model.",
        "",
    ]
    if result.guard:
        advice = {"show": "show it", "show_with_warning": "show it with a warning", "withhold": "hold it back"}
        lines += [f"Advice for apps: {advice[result.guard.action]}. {text(result.guard.reason)}", ""]
    if result.context:
        lines += ["Checked for: " + "; ".join(text(line) for line in result.context.lines()), ""]
    if result.question:
        lines += ["## Question", "", text(result.question), ""]

    if result.corrected_answer is not None:
        lines += ["## Corrected answer", ""]
        lines += [text(paragraph) for paragraph in result.corrected_answer.split("\n") if paragraph.strip()]
        lines.append("")
        if result.citations:
            lines += ["Sources:", ""]
            for citation in result.citations:
                published = (
                    f", {citation.published_date.isoformat()}" if citation.published_date else ""
                )
                lines.append(
                    f"{citation.number}. {link(citation.title or citation.domain, citation.url)} "
                    f"({text(citation.domain)}{published})"
                )
            lines.append("")

    lines += ["## Original answer", ""]
    lines += [text(paragraph) for paragraph in result.answer.split("\n") if paragraph.strip()]
    lines += ["", "## Claims", ""]
    for item in result.claims:
        lines += _claim_section(item)

    metrics = result.metrics
    cost = f"${metrics.cost_usd:.4f}"
    if metrics.unpriced_calls:
        cost += f" plus {metrics.unpriced_calls} calls with unknown cost"
    lines += [
        "## Run metrics",
        "",
        f"- Time: {metrics.latency_ms / 1000:.1f} s",
        f"- LLM calls: {metrics.llm_calls} ({metrics.tokens_in} tokens in, "
        f"{metrics.tokens_out} out), cost {cost}",
        f"- Bifrost cache hits: {metrics.cache_hits}",
        f"- Tavily credits: {metrics.tavily_credits}",
    ]
    for event in metrics.fallback_events:
        lines.append(
            f"- Fallback: {event['stage']} served by `{event['provider']}/{event['model']}` "
            f"instead of `{event['primary_provider']}/{event['primary_model']}`"
        )
    return "\n".join(lines) + "\n"
