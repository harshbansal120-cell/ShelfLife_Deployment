"""Autopilot: the autonomous freshness agent.

In manual mode ShelfLife works when asked. In auto mode this agent runs a cycle on
a timer and takes every step a person would otherwise trigger:

1. Re-verify answers whose claims are due for a re-check (by their evidence age, or
   the freshness policy's fixed interval), and answers checked for an older version
   of a context profile.
2. Re-visit the sources each answer relied on. A page that is gone, moved or no
   longer says what was quoted makes its answer due at once.
3. Verify documents that state claims nobody has checked yet.
4. When a claim turns stale, trace its downstream impact and correct every document
   built on it, keeping each previous version.
5. Run regression tests that haven't run within their interval.

Every action is written to an activity log, and stale findings go to the alert
webhook. Each cycle has a budget of checks so a large backlog can't run up costs.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from app import alerts, config, dashboard, history, impact, links, policies, regression, workspace
from app.models import CheckContext, CheckResult
from app.pipeline.orchestrator import PipelineError, run_check

logger = logging.getLogger(__name__)

Mode = Literal["manual", "auto"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_events (
    id TEXT PRIMARY KEY, at TEXT NOT NULL, cycle TEXT NOT NULL, kind TEXT NOT NULL,
    level TEXT NOT NULL, title TEXT NOT NULL, detail TEXT NOT NULL, ref TEXT);
"""

LINK_RECHECK_HOURS = 24
REGRESSION_INTERVAL_HOURS = 24
MAX_EVENTS = 500


class AutopilotSettings(BaseModel):
    mode: Mode = "manual"
    interval_seconds: int = Field(default=300, ge=15, le=86_400)
    # The most checks one cycle may start, to bound spend.
    max_checks_per_cycle: int = Field(default=3, ge=1, le=20)


class AutopilotUpdate(BaseModel):
    mode: Mode | None = None
    interval_seconds: int | None = Field(default=None, ge=15, le=86_400)
    max_checks_per_cycle: int | None = Field(default=None, ge=1, le=20)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_settings() -> AutopilotSettings:
    stored = workspace.get_setting("autopilot")
    if stored:
        return AutopilotSettings.model_validate(stored)
    # Short cycles in the self-contained environment, where nothing costs money.
    return AutopilotSettings(interval_seconds=20 if config.get_settings().demo_mode else 300)


def save_settings(update: AutopilotUpdate) -> AutopilotSettings:
    merged = get_settings().model_copy(update=update.model_dump(exclude_none=True))
    workspace.set_setting("autopilot", merged.model_dump())
    return merged


# --- the activity log ---------------------------------------------------------------


def log_event(cycle: str, kind: str, title: str, detail: str = "", level: str = "info",
              ref: dict[str, Any] | None = None) -> dict[str, Any]:
    event = {"id": workspace.new_id(), "at": workspace.now(), "cycle": cycle, "kind": kind,
             "level": level, "title": title, "detail": detail, "ref": ref}
    workspace.execute(
        "INSERT INTO agent_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (event["id"], event["at"], cycle, kind, level, title, detail, json.dumps(ref) if ref else None),
        schema=SCHEMA,
    )
    workspace.execute(
        "DELETE FROM agent_events WHERE id NOT IN (SELECT id FROM agent_events ORDER BY at DESC LIMIT ?)",
        (MAX_EVENTS,), schema=SCHEMA,
    )
    return event


def events(limit: int = 60) -> list[dict[str, Any]]:
    rows = workspace.query("SELECT * FROM agent_events ORDER BY at DESC LIMIT ?", (limit,), schema=SCHEMA)
    return [{**row, "ref": json.loads(row["ref"]) if row["ref"] else None} for row in rows]


# --- what is due ------------------------------------------------------------------------


def _latest_checks(checks: list[CheckResult]) -> dict[str, CheckResult]:
    latest: dict[str, CheckResult] = {}
    for check in sorted(checks, key=lambda c: c.checked_at or datetime.min.replace(tzinfo=timezone.utc)):
        latest[history.answer_key(check.answer)] = check
    return latest


def due_checks(checks: list[CheckResult], today: date) -> list[tuple[CheckResult, str]]:
    """Answers to re-verify now, each with the reason, most urgent first."""
    due: dict[str, tuple[CheckResult, str]] = {}
    latest = _latest_checks(checks)
    by_id = {check.id: check for check in latest.values()}
    for item in history.watchlist(list(latest.values()), today, 0):
        check = by_id.get(item["check_id"])
        if check and check.id not in due:
            due[check.id] = (check, f"“{item['claim_text']}” was due for a re-check on {item['recheck_by']}")
    for alert in dashboard.drift(list(latest.values())):
        for summary in alert["checks"]:
            check = by_id.get(summary["id"])
            if check and check.id not in due:
                due[check.id] = (check, f"the context profile “{alert['profile_name']}” changed")
    flagged = workspace.get_setting("autopilot_link_flags", {})
    for check_id, reason in flagged.items():
        check = by_id.get(check_id)
        if check and check.id not in due:
            due[check.id] = (check, reason)
    return list(due.values())


def _links_due(checks: dict[str, CheckResult]) -> list[CheckResult]:
    visited = workspace.get_setting("autopilot_links_checked", {})
    horizon = _now() - timedelta(hours=LINK_RECHECK_HOURS)
    due = []
    for check in checks.values():
        last = visited.get(check.id)
        if not links.items_for_check(check):
            continue
        if last is None or datetime.fromisoformat(last) < horizon:
            due.append(check)
    return due


def _tests_due() -> list[dict[str, Any]]:
    horizon = _now() - timedelta(hours=REGRESSION_INTERVAL_HOURS)
    return [
        test for test in workspace.list_tests()
        if test["last_run"] is None or datetime.fromisoformat(test["last_run"]["ran_at"]) < horizon
    ]


def pending(today: date | None = None) -> dict[str, Any]:
    """What the next cycle would work on, for the status panel."""
    today = today or date.today()
    checks = history.store().recent(500)
    latest = _latest_checks(checks)
    index = impact.build_index(checks)
    documents = [impact.quick_status(doc, index) for doc in impact.list_documents()]
    return {
        "due_answers": len(due_checks(checks, today)),
        "links_to_visit": len(_links_due(latest)),
        "documents_to_update": sum(1 for status in documents if status == "needs_update"),
        "documents_to_verify": sum(1 for status in documents if status == "unverified"),
        "tests_due": len(_tests_due()),
    }


# --- the cycle ------------------------------------------------------------------------------


class Autopilot:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()
        self._lock = asyncio.Lock()
        self.last_cycle: dict[str, Any] | None = None
        self.next_cycle_at: datetime | None = None

    @property
    def running(self) -> bool:
        return self._lock.locked()

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    def poke(self) -> None:
        """Re-read the settings now, e.g. after switching to auto."""
        self._wake.set()

    async def _loop(self) -> None:
        while True:
            settings = get_settings()
            if settings.mode == "auto":
                try:
                    await self.run_cycle("auto")
                except Exception:
                    logger.exception("Autopilot cycle failed")
                self.next_cycle_at = _now() + timedelta(seconds=settings.interval_seconds)
                timeout = settings.interval_seconds
            else:
                self.next_cycle_at = None
                timeout = None
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout)
            except TimeoutError:
                pass

    async def run_cycle(self, trigger: str) -> dict[str, Any]:
        async with self._lock:
            return await self._cycle(trigger)

    async def _cycle(self, trigger: str) -> dict[str, Any]:
        cycle = workspace.new_id()
        started = _now()
        settings = get_settings()
        budget = settings.max_checks_per_cycle
        actions = 0
        log_event(cycle, "cycle", "Cycle started",
                  "Started automatically." if trigger == "auto" else "Started by hand.")

        # 1 and 2: sources that disappeared make their answer due at once.
        checks = history.store().recent(500)
        latest = _latest_checks(checks)
        actions += await self._visit_links(cycle, latest)

        # Re-verify due answers, within the budget.
        for check, reason in due_checks(history.store().recent(500), date.today())[:budget]:
            if await self._recheck(cycle, check, reason):
                actions += 1
                budget -= 1

        # 3: documents with claims nobody has checked.
        for document in impact.list_documents():
            if budget <= 0:
                break
            analysis = await impact.analyze_document(document)
            if analysis["status"] == "unverified":
                if await self._verify_document(cycle, document):
                    actions += 1
                    budget -= 1

        # 4: newly stale claims, their impact, and the documents built on them.
        actions += await self._propagate(cycle)

        # 5: regression tests.
        for test in _tests_due()[: max(budget, 0)]:
            actions += await self._run_test(cycle, test)

        summary = {
            "id": cycle, "trigger": trigger, "started_at": started.isoformat(),
            "finished_at": _now().isoformat(), "actions": actions,
        }
        log_event(cycle, "cycle", "Cycle finished",
                  f"{actions} action{'s' if actions != 1 else ''} taken." if actions else "Everything is up to date.",
                  level="success" if actions else "info")
        self.last_cycle = summary
        return summary

    async def _visit_links(self, cycle: str, latest: dict[str, CheckResult]) -> int:
        visited = workspace.get_setting("autopilot_links_checked", {})
        flagged = workspace.get_setting("autopilot_link_flags", {})
        actions = 0
        for check in _links_due(latest)[:3]:
            results = await links.check_links(links.items_for_check(check))
            visited[check.id] = _now().isoformat()
            broken = [r for r in results if r["status"] in ("gone", "changed", "moved") and r.get("claim_id")]
            actions += 1
            if broken:
                first = broken[0]
                reason = f"{len(broken)} source{'s' if len(broken) != 1 else ''} it relied on changed ({first['status']}: {first['url']})"
                flagged[check.id] = reason
                log_event(cycle, "links", "Evidence links changed", reason.capitalize() + ".",
                          level="warning", ref={"type": "check", "id": check.id})
            else:
                log_event(cycle, "links", "Evidence links still hold",
                          f"{len(results)} link{'s' if len(results) != 1 else ''} visited for “{_short(check)}”.",
                          ref={"type": "check", "id": check.id})
        workspace.set_setting("autopilot_links_checked", visited)
        workspace.set_setting("autopilot_link_flags", flagged)
        return actions

    async def _recheck(self, cycle: str, check: CheckResult, reason: str) -> bool:
        context = check.context
        profile_version = check.profile_version
        if check.profile_id:
            profile = workspace.get_profile(check.profile_id)
            if profile:
                context = CheckContext.model_validate(profile["context"])
                profile_version = profile["version"]
        try:
            result = await run_check(
                check.answer, question=check.question, context=context, profile_id=check.profile_id,
                profile_version=profile_version, policy=policies.resolve(check.policy_id), trigger="autopilot",
            )
        except PipelineError as exc:
            log_event(cycle, "recheck", "Re-verification failed", str(exc), level="warning",
                      ref={"type": "check", "id": check.id})
            return False
        history.store().save(result)
        flags = workspace.get_setting("autopilot_link_flags", {})
        if flags.pop(check.id, None) is not None:
            workspace.set_setting("autopilot_link_flags", flags)
        before = {item.claim.passport_id: item.verdict for item in check.claims}
        newly_stale = [item for item in result.claims
                       if item.verdict == "stale" and before.get(item.claim.passport_id) != "stale"]
        detail = f"Re-verified because {reason}. "
        if newly_stale:
            detail += "Now out of date: " + "; ".join(
                f"{item.claim.text} (now {item.current_value})" if item.current_value else item.claim.text
                for item in newly_stale
            )
        else:
            stale = result.verdict_counts.get("stale", 0)
            detail += f"No new changes ({stale} stale claim{'s' if stale != 1 else ''} already known)." if stale else "Every claim still holds."
        log_event(cycle, "recheck", f"Re-verified “{_short(result)}”", detail,
                  level="warning" if newly_stale else "success", ref={"type": "check", "id": result.id})
        await alerts.send_stale_alert(result)
        return True

    async def _verify_document(self, cycle: str, document: dict[str, Any]) -> bool:
        try:
            result = await run_check(document["text"], question=document["title"],
                                     policy=policies.resolve(None), trigger="autopilot")
        except PipelineError as exc:
            log_event(cycle, "document", "Document verification failed", str(exc), level="warning",
                      ref={"type": "document", "id": document["id"]})
            return False
        history.store().save(result)
        stale = result.verdict_counts.get("stale", 0)
        log_event(cycle, "document", f"Verified “{document['title']}”",
                  f"Checked {len(result.claims)} claims; {stale} out of date." if stale else f"Checked {len(result.claims)} claims; all current.",
                  level="warning" if stale else "success", ref={"type": "document", "id": document["id"]})
        return True

    async def _propagate(self, cycle: str) -> int:
        """Trace each claim that turned stale since the last cycle, then fix documents."""
        actions = 0
        index = impact.build_index()
        known = set(workspace.get_setting("autopilot_known_stale", []))
        stale_now = {pid for pid, r in index.latest.items() if r.verdict == "stale"}
        for pid in sorted(stale_now - known):
            report = impact.impact_report(pid, index)
            if report is None:
                continue
            counts = report["counts"]
            log_event(cycle, "impact", "Traced the impact of a stale claim",
                      f"{report['claim']['text']} Affects {counts['claims']} dependent claim(s), "
                      f"{counts['documents']} document(s) and {counts['answers']} answer(s).",
                      level="warning" if counts["total"] else "info", ref={"type": "claim", "id": pid})
            await alerts.send_impact_alert(report)
            known.add(pid)
            actions += 1
        # A claim that is fresh again and later goes stale is traced again.
        workspace.set_setting("autopilot_known_stale", sorted(known & stale_now))

        for document in impact.list_documents():
            analysis = await impact.analyze_document(document, index)
            if analysis["status"] != "needs_update":
                continue
            updated = await impact.apply_correction(document["id"], by="autopilot")
            if updated is None or not updated["revisions"]:
                continue
            changes = updated["revisions"][-1]["changes"]
            log_event(cycle, "document", f"Updated “{document['title']}”",
                      "; ".join(f"{c['old'] or c['claim']} → {c['new']}" for c in changes) or "Corrected stale passages.",
                      level="success", ref={"type": "document", "id": document["id"]})
            actions += 1
        return actions

    async def _run_test(self, cycle: str, test: dict[str, Any]) -> int:
        try:
            run = await regression.run_test(test)
        except PipelineError as exc:
            log_event(cycle, "test", f"Regression test “{test['name']}” couldn't run", str(exc),
                      level="warning", ref={"type": "test", "id": test["id"]})
            return 0
        log_event(cycle, "test", f"Regression test “{test['name']}” {'passed' if run['passed'] else 'failed'}",
                  "; ".join(run["problems"]) or "The model's answer is current.",
                  level="success" if run["passed"] else "warning", ref={"type": "test", "id": test["id"]})
        return 1


def _short(check: CheckResult) -> str:
    text = check.question or " ".join(check.answer.split())
    return text if len(text) <= 70 else text[:69].rstrip() + "…"


autopilot = Autopilot()


def status() -> dict[str, Any]:
    settings = get_settings()
    return {
        **settings.model_dump(),
        "running": autopilot.running,
        "last_cycle": autopilot.last_cycle,
        "next_cycle_at": autopilot.next_cycle_at.isoformat() if autopilot.next_cycle_at else None,
        "pending": pending(),
        "events": events(),
    }
