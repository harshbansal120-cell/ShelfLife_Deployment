"""Try other scoring constants on the last evaluation run, without new API calls.

Re-scores the evidence saved in eval/results.json across a grid of half-life
scales, stale cut-offs and minimum-evidence levels, and prints the best settings.

    cd backend
    uv run python ../scripts/eval_tune.py
    uv run python ../scripts/eval_tune.py --top 15

With a small dataset the best row can be luck. Prefer changes that help by a clear
margin, and copy any you adopt into backend/app/config.py by hand.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.evaluation.metrics import ClaimRecord  # noqa: E402
from app.evaluation.report import percent  # noqa: E402
from app.evaluation.tuning import evaluate_params, sweep  # noqa: E402
from app.pipeline.score import DEFAULT_PARAMS  # noqa: E402


def row_text(label: str, row: dict) -> str:
    params = row["params"]
    return (
        f"{label:<9}{params.half_life_scale:>10}{params.uncertain_threshold:>10}"
        f"{params.min_evidence:>10}{percent(row['precision']):>11}{percent(row['recall']):>9}"
        f"{percent(row['f1']):>7}{percent(row['false_alarm_rate']):>14}"
        f"{percent(row['unverified_rate']):>13}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-score saved evidence with other constants.")
    parser.add_argument("--results", type=Path, default=ROOT / "eval" / "results.json")
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args()

    if not args.results.exists():
        print(f"No {args.results}. Run run_eval.py first.")
        return 1
    data = json.loads(args.results.read_text(encoding="utf-8"))
    ok_items = {run["item_id"] for run in data["runs"] if run["ok"]}
    records = [ClaimRecord(**r) for r in data["records"] if r["item_id"] in ok_items]

    print(
        f"{'':<9}{'half-life':>10}{'stale <':>10}{'min evid':>10}{'precision':>11}"
        f"{'recall':>9}{'F1':>7}{'false alarms':>14}{'unverified':>13}"
    )
    print(row_text("current", evaluate_params(records, DEFAULT_PARAMS)))
    for rank, row in enumerate(sweep(records)[: args.top], start=1):
        print(row_text(f"#{rank}", row))
    print(
        "\n'half-life' multiplies every category's half-life. 'stale <' is the score below "
        "which a claim is stale. Edit backend/app/config.py to adopt a setting."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
