"""Background checks and their replayable event streams.

A check keeps running if the browser disconnects. Events are stored, so a client
that connects late or reconnects still sees everything. Jobs live in memory and
are lost when the server restarts.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal

from app import alerts, config, history, policies
from app.models import CheckContext, CheckRequest, CheckResult
from app.pipeline import orchestrator

logger = logging.getLogger(__name__)


class TooManyChecksError(Exception):
    """The limit on checks running at the same time has been reached."""


@dataclass(frozen=True)
class CheckEvent:
    sequence: int
    name: str
    data: dict[str, Any]


class CheckJob:
    def __init__(self, check_id: str) -> None:
        self.id = check_id
        self.status: Literal["running", "done", "failed"] = "running"
        self.events: list[CheckEvent] = []
        self.result: CheckResult | None = None
        self.error: dict[str, str] | None = None
        self.task: asyncio.Task[None] | None = None
        self._waiters: set[asyncio.Event] = set()

    @property
    def finished(self) -> bool:
        return self.status != "running"

    def publish(self, name: str, data: dict[str, Any]) -> None:
        self.events.append(CheckEvent(len(self.events) + 1, name, data))
        self._wake_subscribers()

    def complete(self, result: CheckResult) -> None:
        self.result = result
        self.status = "done"
        self._wake_subscribers()

    def fail(self, code: str, message: str) -> None:
        self.error = {"code": code, "message": message}
        self.status = "failed"
        self.publish("error", self.error)

    def _wake_subscribers(self) -> None:
        for waiter in self._waiters:
            waiter.set()

    async def stream(
        self, after: int = 0, heartbeat_seconds: float = config.SSE_HEARTBEAT_SECONDS
    ) -> AsyncIterator[CheckEvent | None]:
        """Yield events after sequence number `after`, until the job finishes.

        Yields None when nothing has happened for a while, so the caller can send a
        keep-alive. Stopping this generator has no effect on the check itself.
        """
        index = max(after, 0)
        waiter = asyncio.Event()
        self._waiters.add(waiter)
        try:
            while True:
                # Clear first, so an event published during a yield isn't missed.
                waiter.clear()
                while index < len(self.events):
                    yield self.events[index]
                    index += 1
                if self.finished and index >= len(self.events):
                    return
                try:
                    await asyncio.wait_for(waiter.wait(), heartbeat_seconds)
                except TimeoutError:
                    yield None
        finally:
            self._waiters.discard(waiter)


class CheckStore:
    def __init__(
        self,
        max_active: int = config.MAX_ACTIVE_CHECKS,
        max_stored: int = config.MAX_STORED_CHECKS,
    ) -> None:
        self.max_active = max_active
        self.max_stored = max_stored
        self._jobs: dict[str, CheckJob] = {}

    def get(self, check_id: str) -> CheckJob | None:
        return self._jobs.get(check_id)

    def start(self, request: CheckRequest) -> CheckJob:
        active = sum(not job.finished for job in self._jobs.values())
        if active >= self.max_active:
            raise TooManyChecksError
        job = CheckJob(uuid.uuid4().hex)
        self._jobs[job.id] = job
        self._evict_oldest_finished()
        job.task = asyncio.create_task(self._run(job, request))
        return job

    async def shutdown(self) -> None:
        tasks = [job.task for job in self._jobs.values() if job.task and not job.finished]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _evict_oldest_finished(self) -> None:
        excess = len(self._jobs) - self.max_stored
        if excess <= 0:
            return
        oldest = [job.id for job in self._jobs.values() if job.finished][:excess]
        for check_id in oldest:
            del self._jobs[check_id]

    async def _run(self, job: CheckJob, request: CheckRequest) -> None:
        async def on_event(name: str, data: dict[str, Any]) -> None:
            job.publish(name, data)

        context = request.context
        profile_version = None
        if request.profile_id:
            from app import workspace

            profile = workspace.get_profile(request.profile_id)
            if profile is not None:
                context = CheckContext.model_validate(profile["context"])
                profile_version = profile["version"]
        try:
            result = await orchestrator.run_check(
                request.answer,
                question=request.question,
                answer_date=request.answer_date,
                deep=request.deep,
                use_cache=request.use_cache,
                check_id=job.id,
                context=context,
                profile_id=request.profile_id,
                profile_version=profile_version,
                policy=policies.resolve(request.policy_id),
                on_event=on_event,
            )
        except orchestrator.PipelineError as exc:
            job.fail(exc.code, str(exc))
        except asyncio.CancelledError:
            job.fail("cancelled", "The server stopped before this check finished.")
            raise
        except Exception:
            logger.exception("Check %s failed unexpectedly", job.id)
            job.fail("internal_error", "The check failed unexpectedly.")
        else:
            job.complete(result)
            if isinstance(result, CheckResult):
                try:
                    history.store().save(result)
                except Exception:
                    logger.exception("Could not save check %s to history", job.id)
                await alerts.send_stale_alert(result)
