"""Label evaluation claims by hand, one at a time.

For each claim, look the fact up in a reliable, current source, then record:
  stale  - the answer's value is out of date (give the current value and the URL)
  fresh  - the answer's value is still right (give the URL)
  static - the fact can't go out of date, such as history or a definition

    cd backend
    uv run python ../scripts/eval_label.py --labeller "Your Name"
    uv run python ../scripts/eval_label.py --labeller "Your Name" --recheck-older-than 3

Every change is saved straight away. Press q to stop and resume later.
"""

from __future__ import annotations

import argparse
import os
import sys
import textwrap
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.evaluation.dataset import (  # noqa: E402
    EvalClaim,
    EvalItem,
    apply_label,
    label_problems,
    load_items,
    save_items,
)

DEFAULT_DATASET = ROOT / "data" / "eval" / "stale_answers.jsonl"
MENU = "[s] stale  [f] fresh  [t] static  [e] edit text  [a] add a missed claim  [d] delete  [n] next  [q] quit"


def needs_work(claim: EvalClaim, today: date, recheck_days: int | None) -> bool:
    if label_problems(claim):
        return True
    if recheck_days is not None and claim.gold != "static" and claim.verified_on:
        return (today - claim.verified_on).days > recheck_days
    return False


def ask(prompt: str) -> str:
    return input(prompt).strip()


def label_claim(claim: EvalClaim, gold: str, labeller: str) -> EvalClaim | None:
    while True:
        current = None
        if gold in ("stale", "fresh"):
            hint = "required" if gold == "stale" else "optional, Enter to skip"
            current = ask(f"  Current value according to the source ({hint}): ")
            source = ask("  Source URL: ")
        else:
            source = ""
        try:
            return apply_label(
                claim,
                gold,
                current_value=current,
                source_url=source,
                labeller=labeller,
                today=date.today(),
            )
        except ValueError as exc:
            print(f"  Not saved: {exc}.")
            if ask("  Try again? [Y/n] ").lower() == "n":
                return None


def review_item(item: EvalItem, items: list[EvalItem], path: Path, labeller: str, recheck: int | None) -> bool:
    """Label one item's claims. Returns False when the user quits."""
    index = 0
    shown = False
    while index < len(item.claims):
        claim = item.claims[index]
        if not needs_work(claim, date.today(), recheck):
            index += 1
            continue
        if not shown:
            print("\n" + "=" * 72)
            print(f"{item.id}  ({item.topic or 'no topic'})")
            if item.question:
                print(f"Question: {item.question}")
            print(textwrap.fill(f"Answer: {item.answer}", width=88, subsequent_indent="  "))
            shown = True

        print(f"\nClaim {index + 1} of {len(item.claims)}: {claim.text}")
        if claim.gold:
            print(f"  Current label: {claim.gold} (verified {claim.verified_on}, {claim.source_url})")
        choice = ask(f"  {MENU}\n  > ").lower()

        if choice in ("s", "f", "t"):
            gold = {"s": "stale", "f": "fresh", "t": "static"}[choice]
            labelled = label_claim(claim, gold, labeller)
            if labelled is None:
                continue
            item.claims[index] = labelled
        elif choice == "e":
            text = ask("  New claim text: ")
            if text:
                item.claims[index] = claim.model_copy(update={"text": text})
            continue
        elif choice == "a":
            text = ask("  Text of the missed claim: ")
            if text:
                item.claims.insert(index + 1, EvalClaim(text=text))
        elif choice == "d":
            del item.claims[index]
            save_items(path, items)
            continue
        elif choice == "n":
            index += 1
            continue
        elif choice == "q":
            return False
        else:
            continue
        save_items(path, items)
        index += 1
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Label evaluation claims by hand.")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--labeller", default=os.environ.get("EVAL_LABELLER"), help="your name")
    parser.add_argument(
        "--recheck-older-than", type=int, metavar="DAYS", help="also re-check older labels"
    )
    args = parser.parse_args()

    labeller = args.labeller or ask("Your name (stored as verified_by): ")
    if not labeller:
        print("A name is needed for verified_by.")
        return 1
    items = load_items(args.data)
    if not items:
        print(f"No items in {args.data}. Draft some with eval_build.py first.")
        return 1

    for item in items:
        if not review_item(item, items, args.data, labeller, args.recheck_older_than):
            break

    remaining = sum(1 for item in items for claim in item.claims if label_problems(claim))
    print(f"\nSaved. {remaining} claims still need a label.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
