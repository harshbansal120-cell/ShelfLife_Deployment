"""ShelfLife as an MCP server: freshness checks as tools any AI agent can call.

The Model Context Protocol lets assistants such as Claude, and agent frameworks,
discover and call tools. Exposing ShelfLife this way means an agent can verify its
own answer before replying, look up what a stale fact affects, and register the
documents it writes so they are kept current, with no custom integration.

Two transports share this handler:

- Streamable HTTP: `POST /mcp` on the running API (see routes_freshness.py).
- stdio: `uv run python -m app.mcp_stdio`, for clients that launch servers locally.

Only the JSON-RPC methods tools need are implemented: initialize, ping, tools/list
and tools/call.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from pydantic import ValidationError

from app import agent, alerts, dashboard, history, impact, policies
from app.models import CheckContext, CheckRequest
from app.pipeline.orchestrator import PipelineError, run_check

logger = logging.getLogger(__name__)

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "shelflife", "title": "ShelfLife freshness checks", "version": "0.4.0"}
INSTRUCTIONS = (
    "Before showing an answer that states prices, versions, office holders, laws, statistics or "
    "anything described as current, call verify_answer. If its guard is 'withhold', show the "
    "corrected_answer instead, or say what changed. Register documents you generate from checked "
    "facts with register_document so they are corrected when a fact changes."
)


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


TOOLS: list[dict[str, Any]] = [
    {
        "name": "verify_answer",
        "description": "Check an AI-written answer for out-of-date claims against live sources. Returns a "
                       "freshness score, advice (show, warn or withhold), each stale claim with its current "
                       "value, and a corrected answer with citations.",
        "inputSchema": _schema({
            "answer": {"type": "string", "description": "The answer to check."},
            "question": {"type": "string", "description": "The question it answers, if known."},
            "country": {"type": "string", "description": "The reader's country, for local prices and availability."},
            "policy_id": {"type": "string", "description": "A freshness policy id; see list_policies."},
        }, ["answer"]),
    },
    {
        "name": "impact_of_claim",
        "description": "List everything downstream of a claim: claims that rely on it, answers that state it, "
                       "and documents built on it, with the path that links each.",
        "inputSchema": _schema({"passport_id": {"type": "string", "description": "A claim id such as CLM-1A2B3C."}},
                               ["passport_id"]),
    },
    {
        "name": "stale_claims",
        "description": "Every claim currently known to be stale, with how many claims, answers and documents each affects.",
        "inputSchema": _schema({}, []),
    },
    {
        "name": "register_document",
        "description": "Record a document built from checked facts (a proposal, email, report...), so it is "
                       "flagged and corrected when one of its facts goes stale.",
        "inputSchema": _schema({
            "title": {"type": "string"},
            "kind": {"type": "string", "enum": list(impact.DOCUMENT_KINDS)},
            "text": {"type": "string"},
            "passport_ids": {"type": "array", "items": {"type": "string"},
                             "description": "Claims the document used, if known."},
        }, ["title", "text"]),
    },
    {
        "name": "link_claims",
        "description": "Declare that one claim relies on another, e.g. a library recommendation on a Python "
                       "version. When the upstream claim goes stale, the downstream one is reported as affected.",
        "inputSchema": _schema({
            "upstream": {"type": "string"}, "downstream": {"type": "string"}, "note": {"type": "string"},
        }, ["upstream", "downstream"]),
    },
    {
        "name": "get_claim",
        "description": "A claim's verification passport: every check of it, its sources and its verdict history.",
        "inputSchema": _schema({"passport_id": {"type": "string"}}, ["passport_id"]),
    },
    {
        "name": "watchlist",
        "description": "Claims whose re-check date has passed or falls within the next few days.",
        "inputSchema": _schema({"days": {"type": "integer", "minimum": 0, "maximum": 365}}, []),
    },
    {
        "name": "autopilot",
        "description": "Read the autonomous agent's status, or switch it between 'auto' and 'manual'.",
        "inputSchema": _schema({"mode": {"type": "string", "enum": ["auto", "manual"]}}, []),
    },
    {
        "name": "list_policies",
        "description": "Freshness policies: per kind of fact, how fast it goes stale and how often it is re-checked.",
        "inputSchema": _schema({}, []),
    },
]


class ToolError(Exception):
    """A tool call that failed in a way the agent should be told about."""


async def _verify_answer(args: dict[str, Any]) -> dict[str, Any]:
    request = CheckRequest(
        answer=args.get("answer", ""), question=args.get("question"),
        context=CheckContext(country=args["country"]) if args.get("country") else None,
        policy_id=args.get("policy_id"),
    )
    try:
        result = await run_check(
            request.answer, question=request.question, context=request.context,
            policy=policies.resolve(request.policy_id), trigger="mcp",
        )
    except PipelineError as exc:
        raise ToolError(str(exc)) from exc
    history.store().save(result)
    await alerts.send_stale_alert(result)
    return {
        "check_id": result.id,
        "answer_score": result.answer_score,
        "guard": result.guard.model_dump() if result.guard else None,
        "verdict_counts": result.verdict_counts,
        "stale_claims": [
            {"passport_id": item.claim.passport_id, "claim": item.claim.text, "now": item.current_value,
             "change": item.change.change_type if item.change else None}
            for item in result.claims if item.verdict == "stale"
        ],
        "unverified_claims": [item.claim.text for item in result.claims if item.verdict in ("unverified", "error")],
        "corrected_answer": result.corrected_answer,
        "citations": [citation.model_dump(mode="json") for citation in result.citations],
        "recheck_by": result.recheck_by.isoformat() if result.recheck_by else None,
    }


async def _call(name: str, args: dict[str, Any]) -> Any:
    if name == "verify_answer":
        return await _verify_answer(args)
    if name == "impact_of_claim":
        report = impact.impact_report(str(args.get("passport_id", "")).upper())
        if report is None:
            raise ToolError("No claim with that id has been checked.")
        return report
    if name == "stale_claims":
        return [
            {"claim": r["claim"], "severity": r["severity"], "counts": r["counts"]}
            for r in impact.stale_impacts()[:25]
        ]
    if name == "register_document":
        document = await impact.register_document(impact.DocumentRequest.model_validate(args))
        analysis = await impact.analyze_document(document)
        return impact.document_view(document, analysis)
    if name == "link_claims":
        try:
            return impact.add_edge(impact.EdgeRequest.model_validate(args))
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
    if name == "get_claim":
        passport = dashboard.get_passport(str(args.get("passport_id", "")).upper())
        if passport is None:
            raise ToolError("No claim with that id has been checked.")
        return passport
    if name == "watchlist":
        return history.watchlist(history.store().recent(), date.today(), int(args.get("days", 7)))
    if name == "autopilot":
        if args.get("mode"):
            agent.save_settings(agent.AutopilotUpdate(mode=args["mode"]))
            agent.autopilot.poke()
        state = agent.status()
        return {**state, "events": state["events"][:10]}
    if name == "list_policies":
        return {"default": policies.default_policy_id(),
                "policies": [policies.summary(policy) for policy in policies.list_policies()]}
    raise KeyError(name)


def _result(id_: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _error(id_: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


async def handle(message: Any) -> dict[str, Any] | None:
    """Answer one JSON-RPC message. Notifications get no response."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or "method" not in message:
        return _error(message.get("id") if isinstance(message, dict) else None, -32600, "Invalid request.")
    method = message["method"]
    id_ = message.get("id")
    params = message.get("params") or {}
    if "id" not in message:
        return None  # notifications/initialized and friends
    if method == "initialize":
        asked = params.get("protocolVersion")
        return _result(id_, {
            "protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": INSTRUCTIONS,
        })
    if method == "ping":
        return _result(id_, {})
    if method == "tools/list":
        return _result(id_, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name")
        if name not in {tool["name"] for tool in TOOLS}:
            return _error(id_, -32602, f"Unknown tool: {name}")
        try:
            output = await _call(name, params.get("arguments") or {})
        except (ToolError, ValidationError, KeyError) as exc:
            text = str(exc) if not isinstance(exc, KeyError) else "Not found."
            return _result(id_, {"content": [{"type": "text", "text": text}], "isError": True})
        except Exception:
            logger.exception("MCP tool %s failed", name)
            return _result(id_, {"content": [{"type": "text", "text": "The tool failed unexpectedly."}],
                                 "isError": True})
        payload = json.loads(json.dumps(output, default=str))
        structured = payload if isinstance(payload, dict) else {"items": payload}
        return _result(id_, {
            "content": [{"type": "text", "text": json.dumps(payload, indent=2)}],
            "structuredContent": structured,
            "isError": False,
        })
    return _error(id_, -32601, f"Method not found: {method}")
