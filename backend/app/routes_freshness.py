"""API routes for keeping answers fresh over time: freshness policies, documents and
their downstream impact, the dependency freshness graph, the autopilot agent, and the
MCP endpoint.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import agent, impact, mcp, policies

router = APIRouter()


# --- freshness policies ------------------------------------------------------------


@router.get("/api/policies")
async def list_policies() -> dict[str, Any]:
    return {
        "default": policies.default_policy_id(),
        "policies": [policies.summary(policy) for policy in policies.list_policies()],
    }


@router.post("/api/policies", status_code=status.HTTP_201_CREATED)
async def create_policy(request: policies.PolicyRequest) -> dict[str, Any]:
    try:
        return policies.summary(policies.save_policy(request))
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.put("/api/policies/{policy_id}")
async def update_policy(policy_id: str, request: policies.PolicyRequest) -> dict[str, Any]:
    if policies.get_policy(policy_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No policy with that id.")
    try:
        return policies.summary(policies.save_policy(request, policy_id))
    except PermissionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.delete("/api/policies/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_policy(policy_id: str) -> None:
    try:
        policies.delete_policy(policy_id)
    except PermissionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


class DefaultPolicy(BaseModel):
    policy_id: str


@router.put("/api/policies-default")
async def set_default_policy(request: DefaultPolicy) -> dict[str, Any]:
    try:
        policies.set_default(request.policy_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No policy with that id.") from exc
    return await list_policies()


# --- documents and impact -------------------------------------------------------------


async def _view(document: dict[str, Any], index: impact.Index | None = None) -> dict[str, Any]:
    return impact.document_view(document, await impact.analyze_document(document, index))


@router.get("/api/documents")
async def list_documents() -> dict[str, Any]:
    index = impact.build_index()
    return {"documents": [await _view(document, index) for document in impact.list_documents()]}


@router.post("/api/documents", status_code=status.HTTP_201_CREATED)
async def create_document(request: impact.DocumentRequest) -> dict[str, Any]:
    try:
        document = await impact.register_document(request)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No saved check with that id.") from exc
    return await _view(document)


@router.get("/api/documents/{document_id}")
async def get_document(document_id: str) -> dict[str, Any]:
    document = impact.get_document(document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No document with that id.")
    return await _view(document)


@router.post("/api/documents/{document_id}/apply")
async def apply_document_correction(document_id: str) -> dict[str, Any]:
    document = await impact.apply_correction(document_id, by="user")
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No document with that id.")
    return await _view(document)


@router.delete("/api/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: str) -> None:
    impact.delete_document(document_id)


@router.get("/api/impact")
async def stale_impacts() -> dict[str, Any]:
    return {"items": impact.stale_impacts()}


@router.get("/api/impact/{passport_id}")
async def claim_impact(passport_id: str) -> dict[str, Any]:
    report = impact.impact_report(passport_id.upper())
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No checked claim with that id.")
    return report


@router.get("/api/graph")
async def dependency_graph() -> dict[str, Any]:
    return impact.graph()


@router.get("/api/graph/edges")
async def list_edges() -> dict[str, Any]:
    return {"edges": impact.list_edges()}


@router.post("/api/graph/edges", status_code=status.HTTP_201_CREATED)
async def add_edge(request: impact.EdgeRequest) -> dict[str, Any]:
    try:
        return impact.add_edge(request)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.delete("/api/graph/edges/{edge_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_edge(edge_id: str) -> None:
    impact.delete_edge(edge_id)


# --- autopilot ------------------------------------------------------------------------


@router.get("/api/autopilot")
async def autopilot_status() -> dict[str, Any]:
    return agent.status()


@router.put("/api/autopilot")
async def update_autopilot(update: agent.AutopilotUpdate) -> dict[str, Any]:
    agent.save_settings(update)
    agent.autopilot.poke()
    return agent.status()


@router.post("/api/autopilot/run")
async def run_autopilot_cycle() -> dict[str, Any]:
    """Run one cycle now, in either mode."""
    if agent.autopilot.running:
        raise HTTPException(status.HTTP_409_CONFLICT, "A cycle is already running.")
    summary = await agent.autopilot.run_cycle("manual")
    return {"cycle": summary, **agent.status()}


# --- MCP --------------------------------------------------------------------------------


@router.post("/mcp", response_model=None)
async def mcp_endpoint(request: Request) -> Response:
    """MCP over streamable HTTP. Each POST carries one JSON-RPC message or a batch."""
    try:
        payload = json.loads(await request.body())
    except json.JSONDecodeError:
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error."}})
    if isinstance(payload, list):
        responses = [response for item in payload if (response := await mcp.handle(item)) is not None]
        return JSONResponse(responses) if responses else Response(status_code=status.HTTP_202_ACCEPTED)
    response = await mcp.handle(payload)
    if response is None:
        return Response(status_code=status.HTTP_202_ACCEPTED)
    return JSONResponse(response)


@router.get("/mcp")
async def mcp_stream() -> Response:
    """This server sends no server-initiated messages, so there is no stream to open."""
    return Response(status_code=status.HTTP_405_METHOD_NOT_ALLOWED, headers={"Allow": "POST"})
