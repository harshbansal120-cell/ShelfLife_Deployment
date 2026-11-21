"""Saved checks, and what they reveal over time.

Every finished check from the API is stored. That gives each claim a real history
across re-checks, a watchlist of claims due for re-checking, and a way to find
earlier answers that relied on a claim now found stale.
"""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from app import config
from app.evaluation.matching import MATCH_THRESHOLD, similarity
from app.models import CheckResult

# A stale claim and an earlier claim must be this alike to count as the same fact.
AFFECTED_THRESHOLD = 0.75
TRUSTED_VERDICTS = ("fresh", "uncertain")


def answer_key(answer: str) -> str:
    """The same answer, ignoring case and spacing, gets the same key."""
    return hashlib.sha256(" ".join(answer.split()).casefold().encode()).hexdigest()


def _checked_on(result: CheckResult) -> str:
    return result.checked_at.isoformat() if result.checked_at else result.check_date.isoformat()


class HistoryStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.execute(
            "CREATE TABLE IF NOT EXISTS checks (id TEXT PRIMARY KEY, answer_key TEXT NOT NULL, "
            "checked_at TEXT NOT NULL, result TEXT NOT NULL)"
        )
        connection.execute("CREATE INDEX IF NOT EXISTS checks_answer ON checks (answer_key)")
        return connection

    def save(self, result: CheckResult) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT OR REPLACE INTO checks (id, answer_key, checked_at, result) VALUES (?, ?, ?, ?)",
                (result.id, answer_key(result.answer), _checked_on(result), result.model_dump_json()),
            )

    def get(self, check_id: str) -> CheckResult | None:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT result FROM checks WHERE id = ?", (check_id,)).fetchone()
        return CheckResult.model_validate_json(row[0]) if row else None

    def for_answer(self, answer: str, limit: int = 20) -> list[CheckResult]:
        """Checks of this answer, newest first."""
        return self._query(
            "SELECT result FROM checks WHERE answer_key = ? ORDER BY checked_at DESC LIMIT ?",
            (answer_key(answer), limit),
        )

    def recent(self, limit: int = 200) -> list[CheckResult]:
        """The most recent checks, newest first."""
        return self._query("SELECT result FROM checks ORDER BY checked_at DESC LIMIT ?", (limit,))

    def _query(self, sql: str, params: tuple) -> list[CheckResult]:
        with closing(self._connect()) as connection:
            rows = connection.execute(sql, params).fetchall()
        return [CheckResult.model_validate_json(row[0]) for row in rows]


def store() -> HistoryStore:
    return HistoryStore(config.get_settings().history_path)


def _excerpt(text: str, limit: int = 140) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def claim_timeline(current: CheckResult, others: list[CheckResult]) -> dict[str, Any]:
    """Each time-sensitive claim's verdict in every check of the same answer, oldest first."""
    checks = sorted(
        [current, *(other for other in others if other.id != current.id)], key=_checked_on
    )
    claims = []
    for item in current.claims:
        if item.verdict == "not_time_sensitive":
            continue
        entries = []
        for check in checks:
            if check.id == current.id:
                match = item
            else:
                scored = [
                    (similarity(item.claim.text, other.claim.text), other) for other in check.claims
                ]
                best = max(scored, key=lambda pair: pair[0], default=(0.0, None))
                match = best[1] if best[0] >= MATCH_THRESHOLD else None
            if match is not None:
                entries.append({
                    "check_id": check.id,
                    "checked_at": _checked_on(check),
                    "verdict": match.verdict,
                    "score": match.freshness_score,
                })
        claims.append({"claim_id": item.claim.id, "claim_text": item.claim.text, "entries": entries})
    return {
        "checks": [
            {"id": check.id, "checked_at": _checked_on(check), "answer_score": check.answer_score}
            for check in checks
        ],
        "claims": claims,
    }


def watchlist(checks: list[CheckResult], today: date, window_days: int = 7) -> list[dict[str, Any]]:
    """Claims whose re-check date has passed or falls within the window.

    Only the latest check of each answer counts. A due date doesn't mean the claim
    is wrong, only that its evidence is getting old.
    """
    latest: dict[str, CheckResult] = {}
    for check in sorted(checks, key=_checked_on, reverse=True):
        latest.setdefault(answer_key(check.answer), check)

    items = []
    horizon = today + timedelta(days=window_days)
    for check in latest.values():
        for item in check.claims:
            due = item.recheck_by
            if item.verdict not in TRUSTED_VERDICTS or due is None or due > horizon:
                continue
            items.append({
                "check_id": check.id,
                "checked_at": _checked_on(check),
                "question": check.question,
                "answer_excerpt": _excerpt(check.answer),
                "claim_id": item.claim.id,
                "claim_text": item.claim.text,
                "verdict": item.verdict,
                "recheck_by": due.isoformat(),
                "status": "overdue" if due <= today else "due_soon",
            })
    return sorted(items, key=lambda entry: entry["recheck_by"])


def affected_answers(current: CheckResult, others: list[CheckResult]) -> dict[str, list[dict]]:
    """For each stale claim, earlier answers that stated the same fact and were trusted then."""
    key = answer_key(current.answer)
    stale = [item for item in current.claims if item.verdict == "stale"]
    affected: dict[str, list[dict]] = {}
    for item in stale:
        hits = []
        for check in others:
            if check.id == current.id or answer_key(check.answer) == key:
                continue
            for other in check.claims:
                if other.verdict not in TRUSTED_VERDICTS:
                    continue
                if similarity(item.claim.text, other.claim.text) >= AFFECTED_THRESHOLD:
                    hits.append({
                        "check_id": check.id,
                        "checked_at": _checked_on(check),
                        "answer_excerpt": _excerpt(check.answer),
                        "claim_text": other.claim.text,
                        "verdict": other.verdict,
                    })
                    break
        if hits:
            affected[item.claim.id] = hits
    return affected
