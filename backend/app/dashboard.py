"""Read-only views over saved checks: the dashboard, the claim registry (passports),
context drift, and the evaluation results.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Any

from app import config, history, workspace
from app.models import CheckResult
from app.passport import passport_id

TRUSTED = ("fresh", "uncertain")


def _checked_on(result: CheckResult) -> str:
    return result.checked_at.isoformat() if result.checked_at else result.check_date.isoformat()


def _excerpt(text: str, limit: int = 120) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def check_summary(result: CheckResult) -> dict[str, Any]:
    return {
        "id": result.id,
        "checked_at": _checked_on(result),
        "question": result.question,
        "answer_excerpt": _excerpt(result.answer),
        "answer_score": result.answer_score,
        "verdict_counts": result.verdict_counts,
        "guard": result.guard.action if result.guard else None,
        "profile_id": result.profile_id,
    }


def drift(checks: list[CheckResult]) -> list[dict[str, Any]]:
    """Checks made with an older version of a context profile than the current one."""
    profiles = {profile["id"]: profile for profile in workspace.list_profiles()}
    alerts: dict[str, dict[str, Any]] = {}
    for check in checks:
        profile = profiles.get(check.profile_id or "")
        if profile and (check.profile_version or 0) < profile["version"]:
            alert = alerts.setdefault(profile["id"], {
                "profile_id": profile["id"], "profile_name": profile["name"],
                "context": profile["context"], "checks": [],
            })
            alert["checks"].append(check_summary(check))
    return list(alerts.values())


def dashboard(today: date) -> dict[str, Any]:
    checks = history.store().recent(500)
    claims = [item for check in checks for item in check.claims if item.verdict != "not_time_sensitive"]
    verdicts = Counter(item.verdict for item in claims)
    by_category: dict[str, Counter] = defaultdict(Counter)
    for item in claims:
        by_category[item.claim.category][item.verdict] += 1

    daily = []
    for offset in range(13, -1, -1):
        day = today - timedelta(days=offset)
        day_checks = [c for c in checks if _checked_on(c)[:10] == day.isoformat()]
        daily.append({
            "date": day.isoformat(),
            "checks": len(day_checks),
            "stale": sum(item.verdict == "stale" for c in day_checks for item in c.claims),
        })

    metrics = [check.metrics for check in checks]
    alerts = [
        {"kind": "withheld", "check_id": c.id, "text": c.guard.reason, "answer_excerpt": _excerpt(c.answer, 90)}
        for c in checks[:50]
        if c.guard and c.guard.action == "withhold"
    ][:5]
    return {
        "demo_mode": config.get_settings().demo_mode,
        "totals": {
            "checks": len(checks),
            "claims_checked": len(claims),
            "verdicts": dict(verdicts),
            "stale_rate": verdicts["stale"] / len(claims) if claims else None,
        },
        "by_category": {category: dict(counts) for category, counts in sorted(by_category.items())},
        "daily": daily,
        "recent": [check_summary(check) for check in checks[:8]],
        "watchlist": history.watchlist(checks, today, 14),
        "drift": drift(checks),
        "alerts": alerts,
        "usage": {
            "llm_calls": sum(m.llm_calls for m in metrics),
            "tokens": sum(m.tokens_in + m.tokens_out for m in metrics),
            "cost_usd": round(sum(m.cost_usd for m in metrics), 6),
            "unpriced_calls": sum(m.unpriced_calls for m in metrics),
            "cache_hits": sum(m.cache_hits for m in metrics),
            "fallbacks": sum(len(m.fallback_events) for m in metrics),
            "tavily_credits": sum(m.tavily_credits for m in metrics),
            "avg_latency_ms": round(sum(m.latency_ms for m in metrics) / len(metrics)) if metrics else None,
        },
    }


def registry(checks: list[CheckResult]) -> dict[str, dict[str, Any]]:
    """Every claim ever checked, grouped into one passport per claim."""
    passports: dict[str, dict[str, Any]] = {}
    for check in sorted(checks, key=_checked_on):
        for item in check.claims:
            pid = item.claim.passport_id or passport_id(item.claim.text)
            entry = {
                "check_id": check.id,
                "checked_at": _checked_on(check),
                "verdict": item.verdict,
                "score": item.freshness_score,
                "current_value": item.current_value,
            }
            passport = passports.setdefault(pid, {
                "id": pid,
                "first_checked": entry["checked_at"],
                "answers": set(),
                "history": [],
            })
            passport["history"].append(entry)
            passport["answers"].add(history.answer_key(check.answer))
            sources = sorted({
                e.domain for e in item.evidence if e.stance != "irrelevant" and e.counted
            })
            passport.update({
                "text": item.claim.text,
                "category": item.claim.category,
                "kind": item.claim.kind,
                "status": item.verdict,
                "score": item.freshness_score,
                "current_value": item.current_value,
                "last_checked": entry["checked_at"],
                "recheck_by": item.recheck_by.isoformat() if item.recheck_by else None,
                "sources": sources or passport.get("sources", []),
                "authority": max((e.authority for e in item.evidence if e.stance != "irrelevant"), default=None),
            })
    for passport in passports.values():
        passport["checks"] = len(passport["history"])
        passport["answers"] = len(passport["answers"])
    return passports


def list_passports(status: str | None = None, query: str | None = None) -> list[dict[str, Any]]:
    passports = registry(history.store().recent(500)).values()
    rows = [
        {key: value for key, value in passport.items() if key != "history"}
        for passport in passports
        if (not status or passport["status"] == status)
        and (not query or query.casefold() in passport["text"].casefold())
    ]
    return sorted(rows, key=lambda row: row["last_checked"], reverse=True)


def get_passport(pid: str) -> dict[str, Any] | None:
    return registry(history.store().recent(500)).get(pid)


def evaluation() -> dict[str, Any]:
    path = config.ROOT_DIR / "eval" / "results.json"
    if not path.exists():
        return {"available": False}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {"available": True, "summary": data["summary"], "meta": data["meta"]}
