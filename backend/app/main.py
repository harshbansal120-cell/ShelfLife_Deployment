"""FastAPI app and routes."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from datetime import date

from fastapi import FastAPI, Header, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from app import agent, config, demo, history, llm, search
from app.export import to_markdown
from app.routes import router as workspace_router
from app.routes_freshness import router as freshness_router
from app.jobs import CheckEvent, CheckJob, CheckStore, TooManyChecksError
from app.models import (
    CheckCreated,
    CheckRequest,
    CheckResult,
    GenerateStaleRequest,
    GenerateStaleResponse,
)
from app.pipeline.generate import generate_stale_answer
from app.pipeline.orchestrator import PipelineError

STATUS_BY_ERROR_CODE = {
    "not_configured": status.HTTP_503_SERVICE_UNAVAILABLE,
    "budget_exceeded": status.HTTP_402_PAYMENT_REQUIRED,
}

checks = CheckStore()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if config.get_settings().demo_mode:
        await demo.seed()
    agent.autopilot.start()
    yield
    await agent.autopilot.stop()
    await checks.shutdown()


app = FastAPI(title="ShelfLife API", version="0.4.0", lifespan=lifespan)
app.include_router(workspace_router)
app.include_router(freshness_router)

if config.get_settings().demo_mode:
    demo.activate()
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.get_settings().cors_origins_list,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Last-Event-ID", "Mcp-Session-Id", "Mcp-Protocol-Version"],
)


@app.get("/api/health")
async def health(response: Response) -> dict[str, Any]:
    """Report whether Bifrost and Tavily are reachable. Returns 503 if either isn't."""
    bifrost, tavily = await asyncio.gather(llm.health(), search.health())
    healthy = bifrost["ok"] and tavily["ok"]
    response.status_code = 200 if healthy else 503
    return {
        "status": "ok" if healthy else "degraded",
        "bifrost": bifrost,
        "tavily": tavily,
        "missing_settings": config.get_settings().missing_required(),
        "demo_mode": config.get_settings().demo_mode,
    }


@app.post("/api/checks", status_code=status.HTTP_202_ACCEPTED)
async def create_check(request: CheckRequest) -> CheckCreated:
    """Start a check in the background and return its id."""
    missing = config.get_settings().missing_required()
    if missing:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"Missing settings in .env: {', '.join(missing)}.",
        )
    try:
        job = checks.start(request)
    except TooManyChecksError as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many checks are running. Try again when one has finished.",
        ) from exc
    return CheckCreated(check_id=job.id)


@app.post("/api/verify")
async def verify(request: CheckRequest) -> CheckResult:
    """Check an answer in one call and return the full result when it's done.

    For apps that want a single request instead of following the event stream.
    """
    created = await create_check(request)
    job = checks.get(created.check_id)
    await job.task
    if job.status != "done" or job.result is None:
        error = job.error or {"code": "internal_error", "message": "The check failed."}
        code = STATUS_BY_ERROR_CODE.get(error["code"], status.HTTP_502_BAD_GATEWAY)
        raise HTTPException(code, error["message"])
    return job.result


@app.get("/api/checks/{check_id}", response_model=None)
async def get_check(check_id: str) -> CheckResult | JSONResponse:
    """Return the finished result. A running check returns 202 with its status."""
    if checks.get(check_id) is None:
        saved = history.store().get(check_id)
        if saved is not None:
            return saved
    job = _get_job(check_id)
    if job.status == "done":
        return job.result
    if job.status == "running":
        return JSONResponse(
            {"check_id": job.id, "status": "running"}, status.HTTP_202_ACCEPTED
        )
    return JSONResponse(
        {"check_id": job.id, "status": "failed", "error": job.error},
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


@app.get("/api/checks/{check_id}/events", response_model=None)
async def check_events(
    check_id: str, last_event_id: str | None = Header(default=None)
) -> Response:
    """Stream a check's progress as server-sent events, replaying what was missed."""
    job = _get_job(check_id)
    after = _parse_event_id(last_event_id)
    if job.finished and after >= len(job.events):
        # 204 tells a browser's EventSource to stop reconnecting.
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return StreamingResponse(
        _event_stream(job, after),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/checks/{check_id}/export", response_model=None)
async def export_check(check_id: str, format: str = "md") -> Response:
    """Download a finished check as a Markdown report or as JSON."""
    result = _finished_result(check_id)
    name = f"shelflife-{check_id[:8]}"
    if format == "json":
        body, media_type, filename = result.model_dump_json(indent=2), "application/json", f"{name}.json"
    elif format == "md":
        body, media_type, filename = to_markdown(result), "text/markdown; charset=utf-8", f"{name}.md"
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "format must be md or json.")
    return Response(
        body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/checks/{check_id}/history")
async def check_history(check_id: str) -> dict[str, Any]:
    """Each claim's verdict across every check of the same answer, oldest first."""
    result = _finished_result(check_id)
    return history.claim_timeline(result, history.store().for_answer(result.answer))


@app.get("/api/checks/{check_id}/affected")
async def affected(check_id: str) -> dict[str, Any]:
    """Earlier answers that stated a fact this check found stale."""
    result = _finished_result(check_id)
    return {"claims": history.affected_answers(result, history.store().recent())}


@app.get("/api/watchlist")
async def get_watchlist(days: int = 7) -> dict[str, Any]:
    """Claims from saved checks whose re-check date has passed or is coming up."""
    window = max(0, min(days, 3650))
    return {"items": history.watchlist(history.store().recent(), date.today(), window)}


@app.get("/api/budget")
async def budget() -> dict[str, Any]:
    """The virtual key's budget and spend, as Bifrost tracks them."""
    try:
        return await llm.budget_status()
    except llm.LLMError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@app.post("/api/generate-stale")
async def generate_stale(request: GenerateStaleRequest) -> GenerateStaleResponse:
    """Demo helper: answer a question from an older model's memory."""
    try:
        return await generate_stale_answer(request.question)
    except PipelineError as exc:
        code = STATUS_BY_ERROR_CODE.get(exc.code, status.HTTP_502_BAD_GATEWAY)
        raise HTTPException(code, str(exc)) from exc


def _finished_result(check_id: str) -> CheckResult:
    """A finished check from memory, or from history after a restart."""
    job = checks.get(check_id)
    if job is None:
        saved = history.store().get(check_id)
        if saved is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No check with that id.")
        return saved
    if job.status != "done" or job.result is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The check hasn't finished.")
    return job.result


def _get_job(check_id: str) -> CheckJob:
    job = checks.get(check_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No check with that id.")
    return job


def _parse_event_id(value: str | None) -> int:
    try:
        return max(int(value), 0) if value else 0
    except ValueError:
        return 0


def format_sse(event: CheckEvent) -> str:
    data = json.dumps(event.data, separators=(",", ":"))
    return f"id: {event.sequence}\nevent: {event.name}\ndata: {data}\n\n"


async def _event_stream(job: CheckJob, after: int) -> AsyncIterator[str]:
    # An immediate comment makes proxies and browsers open the stream right away.
    yield ": connected\n\n"
    async for event in job.stream(after):
        yield ": keep-alive\n\n" if event is None else format_sse(event)
