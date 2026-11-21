"""Write eval/results.md from an evaluation summary."""

from __future__ import annotations

from typing import Any

VERDICT_COLUMNS = (
    "stale",
    "uncertain",
    "fresh",
    "unverified",
    "error",
    "not_time_sensitive",
    "not_extracted",
)


README_START = "<!-- eval-results:start -->"
README_END = "<!-- eval-results:end -->"


def readme_block(summary: dict[str, Any], meta: dict[str, Any]) -> str:
    """The short results table that run_eval.py writes into the README."""
    strict = summary["stale_strict"]
    gold = summary["gold_counts"]
    latency = summary["avg_latency_ms"]
    lines = [
        f"Measured on {meta['run_date']}: {summary['answers']} answers, "
        f"{summary['gold_claims']} human-labelled claims ({gold.get('stale', 0)} stale, "
        f"{gold.get('fresh', 0)} fresh, {gold.get('static', 0)} static). "
        "Full report: [eval/results.md](eval/results.md).",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Stale detection precision | {percent(strict['precision'])} |",
        f"| Stale detection recall | {percent(strict['recall'])} |",
        f"| Stale detection F1 | {percent(strict['f1'])} |",
        f"| False alarms on fresh claims | {percent(summary['false_alarm_rate'])} |",
        f"| Claim extraction recall | {percent(summary['extraction_recall'])} |",
        f"| Unverified rate | {percent(summary['unverified_rate'])} |",
        f"| Average time per answer | {'n/a' if latency is None else f'{latency / 1000:.1f} s'} |",
        f"| Average LLM cost per answer | {_money(summary['avg_cost_usd'])} |",
    ]
    if meta.get("cache_hit_rate") is not None:
        lines.append(f"| Bifrost cache hit rate on a second run | {percent(meta['cache_hit_rate'])} |")
    return "\n".join(lines)


def update_readme(readme: str, block: str) -> str:
    """Replace the text between the results markers. Raises ValueError if they're missing."""
    start = readme.find(README_START)
    end = readme.find(README_END)
    if start == -1 or end == -1 or end < start:
        raise ValueError("The README has no eval-results markers.")
    return f"{readme[: start + len(README_START)]}\n{block}\n{readme[end:]}"


def percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.0f}%"


def _money(value: float | None) -> str:
    return "n/a" if value is None else f"${value:.4f}"


def render_markdown(summary: dict[str, Any], meta: dict[str, Any]) -> str:
    strict = summary["stale_strict"]
    lenient = summary["stale_lenient"]
    gold = summary["gold_counts"]
    latency = summary["avg_latency_ms"]
    latency_text = "n/a" if latency is None else f"{latency / 1000:.1f} s"
    credits = summary["avg_tavily_credits"]
    credits_text = "n/a" if credits is None else f"{credits:.1f}"
    cost_note = (
        f" ({summary['unpriced_calls']} calls had no known price, so this is a lower bound)"
        if summary["unpriced_calls"]
        else ""
    )

    lines = [
        "# ShelfLife evaluation",
        "",
        f"Run on {meta['run_date']} against `{meta['dataset']}`: "
        f"{summary['answers']} answers and {summary['gold_claims']} human-labelled claims "
        f"({gold.get('stale', 0)} stale, {gold.get('fresh', 0)} fresh, "
        f"{gold.get('static', 0)} static). Labels were checked between "
        f"{meta['labels_from']} and {meta['labels_to']}.",
        "",
        f"Models: extraction `{meta['model_fast']}`, adjudication `{meta['model_strong']}`.",
        "",
        "## Headline",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Stale detection precision | {percent(strict['precision'])} |",
        f"| Stale detection recall | {percent(strict['recall'])} |",
        f"| Stale detection F1 | {percent(strict['f1'])} |",
        f"| False alarms on fresh claims | {percent(summary['false_alarm_rate'])} |",
        f"| Claim extraction recall | {percent(summary['extraction_recall'])} |",
        f"| Unverified rate | {percent(summary['unverified_rate'])} |",
        f"| Static claims correctly skipped | {percent(summary['static_handled'])} |",
        f"| Average time per answer | {latency_text} |",
        f"| Average LLM cost per answer | {_money(summary['avg_cost_usd'])}{cost_note} |",
        f"| Average Tavily credits per answer | {credits_text} |",
    ]
    if meta.get("cache_hit_rate") is not None:
        lines.append(f"| Bifrost cache hit rate on a second run | {percent(meta['cache_hit_rate'])} |")

    lines += [
        "",
        f"Counting \"uncertain\" as a stale flag too gives precision {percent(lenient['precision'])}, "
        f"recall {percent(lenient['recall'])} and F1 {percent(lenient['f1'])}.",
        "",
        "## Verdicts by gold label",
        "",
        "| Gold \\ predicted | " + " | ".join(VERDICT_COLUMNS) + " |",
        "|---|" + "---|" * len(VERDICT_COLUMNS),
    ]
    for label in ("stale", "fresh", "static"):
        counts = summary["confusion"].get(label, {})
        lines.append(
            f"| {label} | " + " | ".join(str(counts.get(c, 0)) for c in VERDICT_COLUMNS) + " |"
        )

    lines += [
        "",
        "## By topic",
        "",
        "| Topic | Claims | Extraction recall | Precision | Recall | F1 |",
        "|---|---|---|---|---|---|",
    ]
    for topic, row in summary["by_topic"].items():
        lines.append(
            f"| {topic} | {row['claims']} | {percent(row['extraction_recall'])} | "
            f"{percent(row['precision'])} | {percent(row['recall'])} | {percent(row['f1'])} |"
        )

    lines += [
        "",
        "## How these are measured",
        "",
        "- A person labelled every claim as stale, fresh or static against a real source URL. "
        "The labels and sources are in the dataset file.",
        "- Each labelled claim is matched to the closest extracted claim by text similarity. "
        "A labelled claim with no match counts as missed, so it lowers recall.",
        "- Stale detection counts a claim as flagged only when the verdict is \"stale\". "
        "It is measured over claims labelled stale or fresh.",
        "- The unverified rate is the share of matched time-sensitive claims that got "
        "\"unverified\" or \"error\" instead of a verdict.",
        f"- {summary['extra_predictions']} extracted claims had no labelled counterpart. "
        "They are not counted either way.",
    ]
    if summary["failed_answers"]:
        lines.append(
            f"- {summary['failed_answers']} answers failed to run and are left out of every number."
        )
    return "\n".join(lines) + "\n"
