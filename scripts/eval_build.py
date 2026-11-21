"""Draft evaluation items from the question list.

For each question, MODEL_STALE answers from memory and the extractor drafts the
answer's claims. The drafts carry no labels: label them with eval_label.py, and
add any claims the extractor missed, or extraction recall will look better than it is.

    cd backend
    uv run python ../scripts/eval_build.py
    uv run python ../scripts/eval_build.py --limit 5

Items already in the dataset are skipped, so the script can be re-run safely.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import llm  # noqa: E402
from app.evaluation.dataset import EvalClaim, EvalItem, load_items, save_items  # noqa: E402
from app.pipeline.extract import extract_claims  # noqa: E402
from app.pipeline.generate import generate_stale_answer  # noqa: E402
from app.pipeline.metrics import MetricsCollector  # noqa: E402
from app.pipeline.orchestrator import PipelineError  # noqa: E402

DEFAULT_QUESTIONS = ROOT / "data" / "eval" / "questions.jsonl"
DEFAULT_DATASET = ROOT / "data" / "eval" / "stale_answers.jsonl"


def load_questions(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


async def build_item(row: dict) -> EvalItem:
    generated = await generate_stale_answer(row["question"])
    claims = await extract_claims(
        generated.answer, row["question"], None, date.today(), MetricsCollector()
    )
    return EvalItem(
        id=row["id"],
        topic=row.get("topic"),
        question=row["question"],
        answer=generated.answer,
        claims=[EvalClaim(text=claim.text) for claim in claims],
        answer_model=generated.model,
        generated_on=date.today().isoformat(),
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description="Draft unlabelled evaluation items.")
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--limit", type=int, help="draft at most this many new items")
    args = parser.parse_args()

    items = load_items(args.data)
    existing = {item.id for item in items}
    todo = [row for row in load_questions(args.questions) if row["id"] not in existing]
    if args.limit is not None:
        todo = todo[: args.limit]
    print(f"{len(existing)} items already in {args.data.name}; drafting {len(todo)} more.")

    for row in todo:
        try:
            item = await build_item(row)
        except (PipelineError, llm.LLMError) as exc:
            print(f"  {row['id']}: skipped ({exc})")
            continue
        items.append(item)
        save_items(args.data, items)
        print(f"  {row['id']}: {len(item.claims)} draft claims")

    print("Next: label the claims with  uv run python ../scripts/eval_label.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
