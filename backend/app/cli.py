"""Check an answer from the command line.

    uv run python -m app.cli "The answer to check"
    uv run python -m app.cli --file answer.txt --deep
"""

from __future__ import annotations

import argparse
import asyncio
import io
import sys
import textwrap
from datetime import date
from pathlib import Path

from app.export import to_markdown
from app.models import CheckResult, ClaimResult
from app.pipeline.orchestrator import PipelineError, run_check
from app.pipeline.score import confidence_label

CLAIM_WIDTH = 64


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli", description="Check an AI answer for stale claims."
    )
    parser.add_argument("answer", nargs="?", help="the answer text, or - to read standard input")
    parser.add_argument("--file", type=Path, help="read the answer from a text file")
    parser.add_argument("--question", help="the question the answer responds to")
    parser.add_argument(
        "--answer-date", type=date.fromisoformat, help="when the answer was written (YYYY-MM-DD)"
    )
    parser.add_argument("--deep", action="store_true", help="use advanced Tavily search")
    parser.add_argument("--json", action="store_true", help="print the full result as JSON")
    parser.add_argument("--markdown", action="store_true", help="print a Markdown report")
    return parser


def read_answer(args: argparse.Namespace, parser: argparse.ArgumentParser) -> str:
    if args.file and args.answer:
        parser.error("give the answer as text or with --file, not both")
    if args.file:
        try:
            return args.file.read_text(encoding="utf-8")
        except OSError as exc:
            parser.error(f"could not read {args.file}: {exc.strerror}")
    if args.answer == "-":
        return sys.stdin.read()
    if args.answer:
        return args.answer
    parser.error("no answer given")


def format_report(result: CheckResult) -> str:
    lines = [
        f"{'#':<4}{'Verdict':<20}{'Score':>5}  {'Conf':<5}{'Category':<17}Claim",
        "-" * (53 + CLAIM_WIDTH),
    ]
    for item in result.claims:
        lines.append(_table_row(item))

    details = [_claim_details(item) for item in result.claims if item.evidence or _has_note(item)]
    if details:
        lines.extend(["", "Details", "-------", *details])

    if result.edits:
        lines.extend(["", "Corrected answer", "----------------", result.corrected_answer or ""])
        for citation in result.citations:
            lines.append(f"[{citation.number}] {citation.url}")

    lines.extend(["", *_summary(result)])
    return "\n".join(lines)


def _table_row(item: ClaimResult) -> str:
    score = "-" if item.freshness_score is None else str(item.freshness_score)
    confidence = confidence_label(item.confidence) if item.freshness_score is not None else "-"
    claim = textwrap.shorten(item.claim.text, width=CLAIM_WIDTH, placeholder="...")
    return (
        f"{item.claim.id:<4}{item.verdict:<20}{score:>5}  {confidence:<5}"
        f"{item.claim.category:<17}{claim}"
    )


def _has_note(item: ClaimResult) -> bool:
    return item.verdict in ("unverified", "error")


def _claim_details(item: ClaimResult) -> str:
    lines = [f"{item.claim.id} [{item.verdict}] {item.claim.text}"]
    if item.current_value:
        lines.append(f"    Sources now say: {item.current_value}")
    lines.append(f"    Why: {item.explanation}")
    for source in item.evidence:
        if source.stance == "irrelevant":
            continue
        published = source.published_date.isoformat() if source.published_date else "no date"
        lines.append(
            f"    {source.stance:<12}{source.domain} ({published}) "
            f"a={source.authority:.2f} r={source.recency:.2f} w={source.weight:.2f}"
        )
        lines.append(f'      "{source.quote}"')
        lines.append(f"      {source.url}")
    return "\n".join(lines)


def _summary(result: CheckResult) -> list[str]:
    metrics = result.metrics
    score = "n/a" if result.answer_score is None else f"{result.answer_score}/100"
    counts = ", ".join(f"{name}: {count}" for name, count in sorted(result.verdict_counts.items()))
    cost = f"${metrics.cost_usd:.4f}"
    if metrics.unpriced_calls:
        cost += f" plus {metrics.unpriced_calls} call(s) with unknown cost"
    lines = [
        f"Answer freshness: {score}",
        f"Verdicts: {counts or 'no claims found'}",
        f"LLM: {metrics.llm_calls} calls, {metrics.tokens_in} tokens in, "
        f"{metrics.tokens_out} out, {cost}, {metrics.cache_hits} cache hits",
        f"Tavily: {metrics.tavily_credits} credits",
        f"Time: {metrics.latency_ms / 1000:.1f}s",
    ]
    for event in metrics.fallback_events:
        lines.append(
            f"Fallback: {event['stage']} served by {event['provider']}/{event['model']} "
            f"instead of {event['primary_provider']}/{event['primary_model']}"
        )
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    answer = read_answer(args, parser)
    try:
        result = asyncio.run(
            run_check(
                answer,
                question=args.question,
                answer_date=args.answer_date,
                deep=args.deep,
            )
        )
    except PipelineError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(result.model_dump_json(indent=2))
    elif args.markdown:
        print(to_markdown(result))
    else:
        print(format_report(result))
    return 0


if __name__ == "__main__":
    # Source text can contain characters the Windows console encoding can't print.
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
