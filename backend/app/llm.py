"""Bifrost client. Every LLM call in ShelfLife goes through chat().

Uses plain httpx rather than a provider SDK so Bifrost's `extra_fields`
(routing_info, cache_debug) reach our metrics.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from app import config

REQUEST_TIMEOUT = httpx.Timeout(120.0, connect=5.0)
HEALTH_TIMEOUT = httpx.Timeout(5.0)

# Tests replace this with httpx.MockTransport.
_transport: httpx.AsyncBaseTransport | None = None

_FENCED_JSON = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)

# What to do about Bifrost's governance errors, keyed by the error `type` it returns.
ERROR_HINTS = {
    "virtual_key_required": (
        "Create a virtual key in the Bifrost dashboard under Virtual Keys, "
        "then set BIFROST_VK in .env."
    ),
    "access_not_found": "Check that BIFROST_VK in .env matches a key in the Bifrost dashboard.",
    "access_blocked": "The virtual key is inactive or has expired. Check it in the Bifrost dashboard.",
    "model_blocked": "Allow this model in the virtual key's settings in the Bifrost dashboard.",
    "provider_blocked": "Allow this provider in the virtual key's settings in the Bifrost dashboard.",
}


class LLMError(Exception):
    """A call through Bifrost failed."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class BudgetExceededError(LLMError):
    """The virtual key's budget has run out (HTTP 402)."""


class LLMValidationError(LLMError):
    """The model's output failed schema validation, including after the retry."""

    def __init__(self, message: str, content: str, result: LLMResult | None = None):
        super().__init__(message)
        self.content = content
        # The failed attempts still cost tokens, so metrics need them.
        self.result = result


@dataclass
class LLMResult:
    content: str
    parsed: BaseModel | None = None
    usage: dict[str, int] = field(default_factory=dict)
    # None means the cost is unknown: Bifrost gave none and the model isn't in PRICE_TABLE.
    cost_usd: float | None = None
    routing_info: dict[str, Any] = field(default_factory=dict)
    cache_debug: dict[str, Any] = field(default_factory=dict)
    latency_ms: int = 0
    attempts: int = 1

    @property
    def served_by(self) -> str | None:
        """The provider/model that actually answered, which may be a fallback."""
        provider = self.routing_info.get("provider")
        model = self.routing_info.get("model")
        if not (provider and model):
            return None
        return model if model.startswith(f"{provider}/") else f"{provider}/{model}"


async def chat(
    stage: str,
    messages: list[dict],
    model: str,
    fallbacks: list[str],
    json_schema: type[BaseModel] | None = None,
    cache: bool = True,
) -> LLMResult:
    """Send one chat request through Bifrost.

    With `json_schema`, the reply is validated and returned in `.parsed`. An invalid
    reply is retried once with the error included; a second failure raises
    LLMValidationError so the caller can mark that claim `error` and carry on.
    """
    if not model:
        raise LLMError(f"No model is configured for stage '{stage}'.")

    if json_schema is None:
        return await _call(stage, messages, model, fallbacks, cache)

    request_messages = _with_schema_instruction(messages, json_schema)
    first = await _call(stage, request_messages, model, fallbacks, cache)
    parsed, error = _parse(first.content, json_schema)
    if error is None:
        first.parsed = parsed
        return first

    retry_messages = [
        *request_messages,
        {"role": "assistant", "content": first.content},
        {
            "role": "user",
            "content": (
                "That reply failed validation:\n"
                f"{error}\n"
                "Reply again with only a corrected JSON object."
            ),
        },
    ]
    second = await _call(stage, retry_messages, model, fallbacks, cache=False)
    result = _merge_attempts(first, second)
    parsed, error = _parse(result.content, json_schema)
    if error is not None:
        raise LLMValidationError(
            f"Stage '{stage}' returned invalid JSON after a retry: {error}",
            result.content,
            result,
        )
    result.parsed = parsed
    return result


async def health() -> dict[str, Any]:
    """Check that Bifrost is reachable and that our virtual key will be accepted."""
    base_url = _base_url()
    try:
        async with httpx.AsyncClient(timeout=HEALTH_TIMEOUT, transport=_transport) as client:
            response = await client.get(f"{base_url}/health")
            if response.status_code != 200:
                return {"ok": False, "url": base_url, "detail": f"HTTP {response.status_code}"}
            key = await _virtual_key_status(client)
    except httpx.HTTPError as exc:
        return {"ok": False, "url": base_url, "detail": f"unreachable ({type(exc).__name__})"}
    if not key["ok"]:
        return {"ok": False, "url": base_url, "detail": key["detail"], "virtual_key": key}
    return {"ok": True, "url": base_url, "detail": "reachable", "virtual_key": key}


async def _virtual_key_status(client: httpx.AsyncClient) -> dict[str, Any]:
    virtual_key = config.get_settings().bifrost_vk
    if not virtual_key:
        enforced = await _virtual_keys_enforced(client)
        if enforced:
            return {
                "ok": False,
                "configured": False,
                "detail": f"Bifrost requires a virtual key. {ERROR_HINTS['virtual_key_required']}",
            }
        return {"ok": True, "configured": False, "detail": "not used"}

    response = await client.get(
        f"{_base_url()}/api/governance/virtual-keys/quota", headers={"x-bf-vk": virtual_key}
    )
    if response.status_code != 200:
        return {
            "ok": False,
            "configured": True,
            "detail": f"Bifrost rejected BIFROST_VK (HTTP {response.status_code}). "
            f"{ERROR_HINTS['access_not_found']}",
        }
    quota = response.json()
    if quota.get("is_active") is False:
        return {"ok": False, "configured": True, "detail": ERROR_HINTS["access_blocked"]}
    return {"ok": True, "configured": True, "detail": f"key '{quota.get('virtual_key_name')}'"}


async def _virtual_keys_enforced(client: httpx.AsyncClient) -> bool:
    """Ask Bifrost whether LLM calls need a virtual key. Unknown counts as no."""
    response = await client.get(f"{_base_url()}/api/session/is-auth-enabled")
    if response.status_code != 200:
        return False
    try:
        return bool(response.json().get("inference_auth_enforced"))
    except (ValueError, AttributeError):
        return False


async def budget_status() -> dict[str, Any]:
    """Return the virtual key's budgets and spend, as Bifrost tracks them."""
    virtual_key = config.get_settings().bifrost_vk
    if not virtual_key:
        return {"configured": False, "budgets": []}
    try:
        async with httpx.AsyncClient(timeout=HEALTH_TIMEOUT, transport=_transport) as client:
            response = await client.get(
                f"{_base_url()}/api/governance/virtual-keys/quota",
                headers={"x-bf-vk": virtual_key},
            )
    except httpx.HTTPError as exc:
        raise LLMError(f"Could not reach Bifrost ({type(exc).__name__}).") from exc
    if response.status_code != 200:
        _raise_for_error(response)
    quota = response.json()
    return {
        "configured": True,
        "name": quota.get("virtual_key_name"),
        "is_active": quota.get("is_active", True),
        "budgets": [
            {
                "max_limit": budget.get("max_limit"),
                "current_usage": budget.get("current_usage", 0),
                "reset_duration": budget.get("reset_duration"),
            }
            for budget in quota.get("budgets") or []
        ],
    }


def _base_url() -> str:
    return config.get_settings().bifrost_url.rstrip("/")


def _headers(stage: str, cache: bool) -> dict[str, str]:
    headers: dict[str, str] = {}
    virtual_key = config.get_settings().bifrost_vk
    if virtual_key:
        headers["x-bf-vk"] = virtual_key
    if cache:
        policy = config.CACHE_POLICIES.get(stage, config.DEFAULT_CACHE_POLICY)
        headers["x-bf-cache-key"] = f"shelflife-{stage}"
        headers["x-bf-cache-ttl"] = policy.ttl
        headers["x-bf-cache-type"] = policy.cache_type
    return headers


async def _call(
    stage: str, messages: list[dict], model: str, fallbacks: list[str], cache: bool
) -> LLMResult:
    body: dict[str, Any] = {"model": model, "messages": messages}
    if fallbacks:
        body["fallbacks"] = fallbacks

    url = f"{_base_url()}/v1/chat/completions"
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, transport=_transport) as client:
            response = await client.post(url, json=body, headers=_headers(stage, cache))
    except httpx.HTTPError as exc:
        raise LLMError(f"Could not reach Bifrost at {url} ({type(exc).__name__}).") from exc
    latency_ms = round((time.perf_counter() - started) * 1000)

    if response.status_code >= 400:
        _raise_for_error(response)

    try:
        data = response.json()
    except ValueError as exc:
        raise LLMError("Bifrost returned a response that isn't JSON.") from exc

    extra_fields = data.get("extra_fields") or {}
    routing_info = extra_fields.get("routing_info") or {}
    cache_debug = extra_fields.get("cache_debug") or {}
    usage = _normalise_usage(data.get("usage") or {})
    return LLMResult(
        content=_message_text(data),
        usage=usage,
        cost_usd=_cost(data, usage, model, routing_info, cache_debug),
        routing_info=routing_info,
        cache_debug=cache_debug,
        latency_ms=latency_ms,
    )


def _raise_for_error(response: httpx.Response) -> None:
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}

    error = body.get("error")
    error_type = body.get("type")
    message: Any = error
    if isinstance(error, dict):
        message = error.get("message")
        error_type = error_type or error.get("type")
    message = str(message or response.text[:300] or "no error message")

    if response.status_code == 402 and (error_type == "budget_exceeded" or "budget" in message.lower()):
        raise BudgetExceededError(message, status_code=402)
    hint = ERROR_HINTS.get(error_type or "")
    if hint:
        message = f"{message.rstrip('.')}. {hint}"
    raise LLMError(f"Bifrost returned HTTP {response.status_code}: {message}", response.status_code)


def _message_text(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if not choices:
        raise LLMError("Bifrost returned a response with no choices.")
    content = (choices[0].get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return ""


def _normalise_usage(usage: dict[str, Any]) -> dict[str, int]:
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    total = int(usage.get("total_tokens") or prompt + completion)
    return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": total}


def _reported_cost(data: dict[str, Any]) -> float | None:
    usage = data.get("usage") or {}
    extra_fields = data.get("extra_fields") or {}
    for candidate in (usage.get("cost"), extra_fields.get("cost")):
        if isinstance(candidate, dict):
            candidate = candidate.get("total_cost")
        if isinstance(candidate, (int, float)) and not isinstance(candidate, bool):
            return float(candidate)
    return None


def _cost(
    data: dict[str, Any],
    usage: dict[str, int],
    requested_model: str,
    routing_info: dict[str, Any],
    cache_debug: dict[str, Any],
) -> float | None:
    if cache_debug.get("cache_hit"):
        return 0.0
    reported = _reported_cost(data)
    # Bifrost reports 0.0 when its price list doesn't know the model, so a zero
    # cost for a call that used tokens means "unknown", not "free".
    if reported is not None and (reported > 0 or usage["total_tokens"] == 0):
        return reported

    # Price the model that actually served the call, which may be a fallback.
    provider = routing_info.get("provider")
    model = routing_info.get("model")
    served = requested_model
    if provider and model:
        served = model if model.startswith(f"{provider}/") else f"{provider}/{model}"
    price = config.PRICE_TABLE.get(served)
    if price is None:
        return None
    return (
        usage["prompt_tokens"] * price.input_per_mtok
        + usage["completion_tokens"] * price.output_per_mtok
    ) / 1_000_000


def _merge_attempts(first: LLMResult, second: LLMResult) -> LLMResult:
    """Report the retry's output, with the cost and time of both attempts."""
    cost = None
    if first.cost_usd is not None and second.cost_usd is not None:
        cost = first.cost_usd + second.cost_usd
    return LLMResult(
        content=second.content,
        usage={key: first.usage[key] + second.usage[key] for key in second.usage},
        cost_usd=cost,
        routing_info=second.routing_info,
        cache_debug=second.cache_debug,
        latency_ms=first.latency_ms + second.latency_ms,
        attempts=first.attempts + second.attempts,
    )


def _with_schema_instruction(messages: list[dict], schema: type[BaseModel]) -> list[dict]:
    # The schema goes in the prompt rather than `response_format`, so the same request
    # works on whichever provider a fallback lands on.
    instruction = (
        "Reply with only a JSON object, with no prose and no code fences. "
        "It must match this JSON Schema:\n"
        f"{json.dumps(schema.model_json_schema(), sort_keys=True)}"
    )
    updated = [dict(message) for message in messages]
    if updated and updated[0].get("role") == "system":
        updated[0]["content"] = f"{updated[0]['content']}\n\n{instruction}"
    else:
        updated.insert(0, {"role": "system", "content": instruction})
    return updated


def _load_json(text: str) -> Any:
    stripped = text.strip()
    fenced = _FENCED_JSON.search(stripped)
    if fenced:
        stripped = fenced.group(1).strip()
    start = stripped.find("{")
    if start == -1:
        raise ValueError("no JSON object found in the reply")
    value, _ = json.JSONDecoder().raw_decode(stripped[start:])
    return value


def _parse(content: str, schema: type[BaseModel]) -> tuple[BaseModel | None, str | None]:
    try:
        return schema.model_validate(_load_json(content)), None
    except ValidationError as exc:
        return None, str(exc)[:2000]
    except ValueError as exc:
        return None, f"invalid JSON: {exc}"
