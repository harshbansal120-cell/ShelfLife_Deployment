"""Run the pipeline over the labelled dataset and write eval/results.md.

    cd backend
    uv run python ../scripts/run_eval.py
    uv run python ../scripts/run_eval.py --second-run      # also measure Bifrost cache hits
    uv run python ../scripts/run_eval.py --limit 5         # quick check

This makes real LLM calls and Tavily searches for every answer. Items with
unlabelled or incomplete claims are skipped and listed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import config  # noqa: E402
from app.evaluation.dataset import DatasetError, check_item, load_items  # noqa: E402
from app.evaluation.metrics import ItemRun, cache_hit_rate, summarise  # noqa: E402
from app.evaluation.report import (  # noqa: E402
    percent,
    readme_block,
    render_markdown,
    update_readme,
)
from app.evaluation.runner import evaluate  # noqa: E402

DEFAULT_DATASET = ROOT / "data" / "eval" / "stale_answers.jsonl"
DEFAULT_OUT = ROOT / "eval"


def progress(run: ItemRun) -> None:
    status = "ok" if run.ok else f"failed: {run.error}"
    print(f"  {run.item_id}: {status}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate ShelfLife on labelled answers.")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--limit", type=int, help="evaluate only the first N valid items")
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--max-label-age", type=int, default=7, metavar="DAYS")
    parser.add_argument(
        "--second-run", action="store_true", help="run again to measure the Bifrost cache"
    )
    parser.add_argument(
        "--update-readme", action="store_true", help="write the headline numbers into README.md"
    )
    args = parser.parse_args()

    settings = config.get_settings()
    if settings.missing_required():
        print(f"Missing settings in .env: {', '.join(settings.missing_required())}")
        return 1
    try:
        items = load_items(args.data)
    except DatasetError as exc:
        print(f"Could not read the dataset: {exc}")
        return 1

    today = date.today()
    valid = []
    for item in items:
        errors, warnings = check_item(item, today, args.max_label_age)
        if errors:
            print(f"Skipping {item.id}: {'; '.join(errors)}")
            continue
        for warning in warnings:
            print(f"Warning, {item.id}: {warning}")
        valid.append(item)
    if args.limit is not None:
        valid = valid[: args.limit]
    if not valid:
        print("No fully labelled items to evaluate. Label some with eval_label.py.")
        return 1

    print(f"Evaluating {len(valid)} answers. This spends LLM tokens and Tavily credits.")
    runs, records = asyncio.run(evaluate(valid, args.concurrency, on_progress=progress))

    second_rate = None
    if args.second_run:
        print("Second run, to measure Bifrost cache hits:")
        second_runs, _ = asyncio.run(evaluate(valid, args.concurrency, on_progress=progress))
        second_rate = cache_hit_rate(second_runs)

    summary = summarise(records, runs)
    dates = sorted(
        str(claim.verified_on) for item in valid for claim in item.claims if claim.verified_on
    )
    meta = {
        "run_date": today.isoformat(),
        "dataset": args.data.relative_to(ROOT).as_posix() if args.data.is_relative_to(ROOT) else str(args.data),
        "labels_from": dates[0] if dates else "n/a",
        "labels_to": dates[-1] if dates else "n/a",
        "model_fast": settings.model_fast,
        "model_strong": settings.model_strong,
        "cache_hit_rate": second_rate,
    }

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "results.md").write_text(render_markdown(summary, meta), encoding="utf-8")
    (args.out / "results.json").write_text(
        json.dumps(
            {
                "meta": meta,
                "summary": summary,
                "runs": [asdict(run) for run in runs],
                "records": [asdict(record) for record in records],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    strict = summary["stale_strict"]
    print(
        f"\nStale detection: precision {percent(strict['precision'])}, "
        f"recall {percent(strict['recall'])}, F1 {percent(strict['f1'])}. "
        f"Extraction recall {percent(summary['extraction_recall'])}, "
        f"unverified {percent(summary['unverified_rate'])}."
    )
    print(f"Wrote {args.out / 'results.md'} and results.json.")

    if args.update_readme:
        readme = ROOT / "README.md"
        try:
            updated = update_readme(readme.read_text(encoding="utf-8"), readme_block(summary, meta))
        except ValueError as exc:
            print(f"README not updated: {exc}")
            return 1
        readme.write_text(updated, encoding="utf-8")
        print("Updated the results in README.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
