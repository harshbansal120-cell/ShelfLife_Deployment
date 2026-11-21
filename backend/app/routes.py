"""API routes for the workspace pages: dashboard, compare, claims, tests, profiles,
links, batch checks, system status and demo mode.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from datetime import date
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, StringConstraints

from app import config, dashboard, demo, history, links, llm, regression, search, workspace
from app.compare import CompareRequest, run_compare
from app.models import AnswerText, CheckContext, QuestionText
from app.pipeline.orchestrator import PipelineError, run_check

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

ERROR_STATUS = {"not_configured": 503, "budget_exceeded": 402}


def _pipeline_error(exc: PipelineError) -> HTTPException:
    return HTTPException(ERROR_STATUS.get(exc.code, status.HTTP_502_BAD_GATEWAY), str(exc))


# --- dashboard and claims ------------------------------------------------------


@router.get("/dashboard")
async def get_dashboard() -> dict[str, Any]:
    return dashboard.dashboard(date.today())


@router.get("/checks")
async def list_checks(limit: int = 50) -> dict[str, Any]:
    checks = history.store().recent(max(1, min(limit, 200)))
    return {"checks": [dashboard.check_summary(check) for check in checks]}


@router.get("/claims")
async def list_claims(status: str | None = None, q: str | None = None) -> dict[str, Any]:
    return {"claims": dashboard.list_passports(status, q)}


@router.get("/claims/{passport_id}")
async def get_claim(passport_id: str) -> dict[str, Any]:
    passport = dashboard.get_passport(passport_id)
    if passport is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No claim with that id.")
    return passport


@router.get("/evaluation")
async def get_evaluation() -> dict[str, Any]:
    return dashboard.evaluation()


# --- compare ---------------------------------------------------------------------


@router.post("/compare")
async def compare(request: CompareRequest) -> dict[str, Any]:
    try:
        return await run_compare(request)
    except PipelineError as exc:
        raise _pipeline_error(exc) from exc


@router.get("/comparisons")
async def comparisons() -> dict[str, Any]:
    return {"comparisons": workspace.list_comparisons()}


# --- regression tests ----------------------------------------------------------


@router.get("/tests")
async def list_tests() -> dict[str, Any]:
    return {"tests": workspace.list_tests()}


@router.post("/tests", status_code=status.HTTP_201_CREATED)
async def create_test(request: regression.TestRequest) -> dict[str, Any]:
    return workspace.save_test(request.name, request.question, request.model, request.must_include)


@router.delete("/tests/{test_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_test(test_id: str) -> None:
    workspace.delete_test(test_id)


@router.get("/tests/{test_id}/runs")
async def test_runs(test_id: str) -> dict[str, Any]:
    return {"runs": workspace.list_runs(test_id)}


@router.post("/tests/{test_id}/run")
async def run_test(test_id: str) -> dict[str, Any]:
    test = workspace.get_test(test_id)
    if test is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No test with that id.")
    try:
        return await regression.run_test(test)
    except PipelineError as exc:
        raise _pipeline_error(exc) from exc


# --- context profiles ------------------------------------------------------------


class ProfileRequest(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
    context: CheckContext


@router.get("/profiles")
async def list_profiles() -> dict[str, Any]:
    drift = {alert["profile_id"]: alert["checks"] for alert in dashboard.drift(history.store().recent(500))}
    return {
        "profiles": [
            {**profile, "drifted_checks": drift.get(profile["id"], [])}
            for profile in workspace.list_profiles()
        ]
    }


@router.post("/profiles", status_code=status.HTTP_201_CREATED)
async def create_profile(request: ProfileRequest) -> dict[str, Any]:
    return workspace.save_profile(request.name, request.context)


@router.put("/profiles/{profile_id}")
async def update_profile(profile_id: str, request: ProfileRequest) -> dict[str, Any]:
    if workspace.get_profile(profile_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No profile with that id.")
    return workspace.save_profile(request.name, request.context, profile_id)


@router.delete("/profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_profile(profile_id: str) -> None:
    workspace.delete_profile(profile_id)


# --- link rot --------------------------------------------------------------------


class LinkRequest(BaseModel):
    check_id: str | None = None
    urls: list[Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]] = Field(
        default_factory=list, max_length=40
    )


@router.post("/links/check")
async def check_links(request: LinkRequest) -> dict[str, Any]:
    items: list[dict[str, Any]] = [{"url": url, "source": "pasted"} for url in request.urls]
    if request.check_id:
        result = history.store().get(request.check_id)
        if result is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No saved check with that id.")
        known = {item["url"] for item in items}
        items += [item for item in links.items_for_check(result) if item["url"] not in known]
    if not items:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Give some URLs or a check with evidence.")
    results = await links.check_links(items)
    counts: dict[str, int] = {}
    for item in results:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return {"results": results, "counts": counts}


# --- batch checks ----------------------------------------------------------------


class BatchItem(BaseModel):
    question: QuestionText | None = None
    answer: AnswerText


class BatchRequest(BaseModel):
    items: list[BatchItem] = Field(min_length=1, max_length=20)
    context: CheckContext | None = None


_batches: dict[str, dict[str, Any]] = {}


async def _run_batch(batch: dict[str, Any], request: BatchRequest) -> None:
    for index, item in enumerate(request.items):
        row = batch["items"][index]
        row["status"] = "running"
        try:
            result = await run_check(item.answer, question=item.question, context=request.context)
            history.store().save(result)
            row.update(status="done", check_id=result.id, verdict_counts=result.verdict_counts,
                       answer_score=result.answer_score)
        except PipelineError as exc:
            row.update(status="failed", error=str(exc))
        except Exception:
            logger.exception("Batch item failed")
            row.update(status="failed", error="The check failed unexpectedly.")
    batch["finished"] = True


@router.post("/batch", status_code=status.HTTP_202_ACCEPTED)
async def start_batch(request: BatchRequest) -> dict[str, Any]:
    if config.get_settings().missing_required():
        raise HTTPException(503, f"Missing settings in .env: {', '.join(config.get_settings().missing_required())}.")
    batch_id = workspace.new_id()
    batch = {
        "id": batch_id,
        "finished": False,
        "items": [{"index": i, "status": "queued", "question": item.question,
                   "answer_excerpt": item.answer[:120]} for i, item in enumerate(request.items)],
    }
    _batches[batch_id] = batch
    batch["task"] = asyncio.create_task(_run_batch(batch, request))
    return {"batch_id": batch_id}


@router.get("/batch/{batch_id}")
async def get_batch(batch_id: str) -> dict[str, Any]:
    batch = _batches.get(batch_id)
    if batch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No batch with that id.")
    return {key: value for key, value in batch.items() if key != "task"}


# --- system ----------------------------------------------------------------------


def _admin_headers() -> dict[str, str]:
    settings = config.get_settings()
    if settings.bifrost_admin_user and settings.bifrost_admin_password:
        token = base64.b64encode(f"{settings.bifrost_admin_user}:{settings.bifrost_admin_password}".encode()).decode()
        return {"Authorization": f"Basic {token}"}
    if settings.bifrost_setup_token:
        return {"X-Bifrost-Setup-Token": settings.bifrost_setup_token}
    return {}


async def _cache_plugin_status() -> dict[str, Any]:
    headers = _admin_headers()
    if not headers:
        return {"known": False, "detail": "Set BIFROST_SETUP_TOKEN in .env to read this."}
    base = config.get_settings().bifrost_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=8, transport=llm._transport) as client:
            response = await client.get(f"{base}/api/plugins", headers=headers)
    except httpx.HTTPError as exc:
        return {"known": False, "detail": f"Bifrost unreachable ({type(exc).__name__})."}
    if response.status_code != 200:
        return {"known": False, "detail": f"Bifrost refused the admin call (HTTP {response.status_code})."}
    payload = response.json()
    plugins = payload.get("plugins") if isinstance(payload, dict) else payload
    cache = next((p for p in plugins or [] if isinstance(p, dict) and p.get("name") == "semantic_cache"), None)
    return {"known": True, "enabled": bool(cache and cache.get("enabled")),
            "detail": "Enabled" if cache and cache.get("enabled") else "Not enabled"}


@router.get("/system")
async def system() -> dict[str, Any]:
    settings = config.get_settings()
    bifrost, tavily, cache = await asyncio.gather(llm.health(), search.health(), _cache_plugin_status())
    try:
        budget = await llm.budget_status()
    except llm.LLMError as exc:
        budget = {"configured": True, "error": str(exc), "budgets": []}
    providers = sorted({name.split("/", 1)[0] for name in [
        settings.model_fast, settings.model_strong, *settings.fallbacks_fast_list, *settings.fallbacks_strong_list
    ] if "/" in name})
    return {
        "demo_mode": settings.demo_mode,
        "bifrost": bifrost,
        "tavily": tavily,
        "cache_plugin": cache,
        "budget": budget,
        "missing_settings": settings.missing_required(),
        "settings": {
            "model_fast": settings.model_fast,
            "model_strong": settings.model_strong,
            "model_stale": settings.model_stale,
            "fallbacks_fast": settings.fallbacks_fast_list,
            "fallbacks_strong": settings.fallbacks_strong_list,
            "providers": providers,
            "use_tavily_extract": settings.use_tavily_extract,
            "tavily_concurrency": settings.tavily_concurrency,
            "search_cache_ttl_hours": settings.search_cache_ttl_hours,
            "alert_webhook": bool(settings.alert_webhook_url),
        },
    }


@router.post("/system/enable-cache")
async def enable_cache() -> dict[str, Any]:
    headers = _admin_headers()
    if not headers:
        raise HTTPException(400, "Set BIFROST_SETUP_TOKEN, or BIFROST_ADMIN_USER and BIFROST_ADMIN_PASSWORD, in .env.")
    base = config.get_settings().bifrost_url.rstrip("/")
    body = {"enabled": True, "path": "", "config": {"dimension": 1, "ttl": "24h", "cache_by_model": True, "cache_by_provider": True}}
    current = await _cache_plugin_status()
    if current.get("enabled"):
        return current
    try:
        async with httpx.AsyncClient(timeout=90, transport=llm._transport) as client:
            response = await client.post(f"{base}/api/plugins", headers=headers, json={"name": "semantic_cache", **body})
            if response.status_code >= 400:
                response = await client.put(f"{base}/api/plugins/semantic_cache", headers=headers, json=body)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Bifrost unreachable ({type(exc).__name__}).") from exc
    if response.status_code >= 400:
        detail = response.text[:300]
        hint = " Bifrost needs a vector store such as Redis in its config.json first." if "store is required" in detail else ""
        raise HTTPException(502, f"Bifrost refused: {detail}{hint}")
    return await _cache_plugin_status()


# --- demo ------------------------------------------------------------------------


@router.get("/demo")
async def demo_info() -> dict[str, Any]:
    return {"active": demo.active(), "scenarios": demo.scenarios() if demo.active() else []}
