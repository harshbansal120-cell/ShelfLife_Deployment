"""Webhook alerts: tell another system when a check finds stale claims."""

from __future__ import annotations

import logging

import httpx

from app import config
from app.models import CheckResult

logger = logging.getLogger(__name__)
# Tests replace this.
_transport: httpx.AsyncBaseTransport | None = None


def stale_alert(result: CheckResult) -> dict | None:
    stale = [item for item in result.claims if item.verdict == "stale"]
    if not stale:
        return None
    return {
        "event": "stale_claims_found",
        "check_id": result.id,
        "checked_at": result.checked_at.isoformat() if result.checked_at else None,
        "question": result.question,
        "answer_score": result.answer_score,
        "guard": result.guard.model_dump() if result.guard else None,
        "stale_claims": [
            {"claim": item.claim.text, "now": item.current_value, "kind": item.claim.kind}
            for item in stale
        ],
        "corrected_answer": result.corrected_answer,
    }


async def send_stale_alert(result: CheckResult) -> bool:
    """POST the alert if a webhook is set and something is stale. Never raises."""
    return await _post(stale_alert(result))


async def send_impact_alert(report: dict) -> bool:
    """Tell the webhook what a newly stale claim affects downstream. Never raises."""
    if not report["counts"]["total"]:
        return False
    return await _post({
        "event": "stale_claim_impact",
        "claim": report["claim"],
        "severity": report["severity"],
        "counts": report["counts"],
        "documents": [{"id": d["id"], "title": d["title"], "kind": d["kind"]} for d in report["documents"]],
        "answers": [a["check_id"] for a in report["answers"]],
    })


async def _post(payload: dict | None) -> bool:
    url = config.get_settings().alert_webhook_url
    if not url or payload is None:
        return False
    try:
        async with httpx.AsyncClient(timeout=5, transport=_transport) as client:
            response = await client.post(url, json=payload)
        return response.status_code < 400
    except httpx.HTTPError:
        logger.warning("Could not deliver the stale-claims alert to the webhook")
        return False
