"""The labelled dataset: one JSON object per line in data/eval/stale_answers.jsonl.

Gold labels and current values come only from a person who checked a real
source. Nothing here fills them in.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, ValidationError

GoldLabel = Literal["stale", "fresh", "static"]
GOLD_LABELS: tuple[GoldLabel, ...] = ("stale", "fresh", "static")


class DatasetError(Exception):
    """The dataset file can't be read."""


class EvalClaim(BaseModel):
    model_config = ConfigDict(extra="allow")

    text: str
    gold: GoldLabel | None = None
    current_value: str | None = None
    source_url: str | None = None
    verified_by: str | None = None
    verified_on: date | None = None


class EvalItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    topic: str | None = None
    question: str | None = None
    answer: str
    answer_date: date | None = None
    claims: list[EvalClaim] = []


def load_items(path: Path) -> list[EvalItem]:
    if not path.exists():
        return []
    items: list[EvalItem] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            items.append(EvalItem.model_validate(json.loads(line)))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise DatasetError(f"{path.name} line {number}: {exc}") from exc
    return items


def save_items(path: Path, items: list[EvalItem]) -> None:
    """Write atomically, so an interrupted save never loses labels."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [item.model_dump_json(exclude_none=False) for item in items]
    handle, temp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as temp:
        temp.write("\n".join(lines) + ("\n" if lines else ""))
    os.replace(temp_name, path)


def is_web_url(value: str | None) -> bool:
    if not value:
        return False
    parts = urlsplit(value.strip())
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def label_problems(claim: EvalClaim) -> list[str]:
    """What stops this claim's label from counting. Empty means it's complete."""
    if claim.gold is None:
        return ["not labelled yet"]
    if claim.gold == "static":
        return []
    problems = []
    if not is_web_url(claim.source_url):
        problems.append("needs a source URL")
    if not claim.verified_by:
        problems.append("needs verified_by")
    if claim.verified_on is None:
        problems.append("needs verified_on")
    if claim.gold == "stale" and not (claim.current_value or "").strip():
        problems.append("a stale label needs the current value")
    return problems


def check_item(
    item: EvalItem, today: date, max_label_age_days: int
) -> tuple[list[str], list[str]]:
    """Return (errors that exclude the item, warnings to show)."""
    errors: list[str] = []
    warnings: list[str] = []
    if not item.answer.strip():
        errors.append("the answer is empty")
    if not item.claims:
        errors.append("has no claims")
    for index, claim in enumerate(item.claims, start=1):
        for problem in label_problems(claim):
            errors.append(f"claim {index} {problem}")
        if claim.verified_on and (today - claim.verified_on).days > max_label_age_days:
            warnings.append(
                f"claim {index} was verified on {claim.verified_on}. Labels go stale too: "
                "re-check it."
            )
    return errors, warnings


def apply_label(
    claim: EvalClaim,
    gold: GoldLabel,
    *,
    current_value: str | None,
    source_url: str | None,
    labeller: str,
    today: date,
) -> EvalClaim:
    """Return the claim with a human's label, or raise ValueError if it's incomplete."""
    labelled = claim.model_copy(
        update={
            "gold": gold,
            "current_value": (current_value or "").strip() or None,
            "source_url": (source_url or "").strip() or None,
            "verified_by": labeller.strip() or None,
            "verified_on": today,
        }
    )
    problems = label_problems(labelled)
    if problems:
        raise ValueError("; ".join(problems))
    return labelled
