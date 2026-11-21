from __future__ import annotations

import json

import httpx
import pytest
from pydantic import BaseModel

from app import config, llm

MESSAGES = [{"role": "user", "content": "hello"}]
FALLBACKS = ["provider-b/fast"]


class Answer(BaseModel):
    value: int


def completion(content: str = "hi", **extra) -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        **extra,
    }


@pytest.fixture
def bifrost(monkeypatch):
    """Queue responses for the fake gateway and record the requests it receives."""

    class FakeBifrost:
        def __init__(self):
            self.requests: list[httpx.Request] = []
            self.responses: list[httpx.Response] = []

        def reply(self, payload: dict, status: int = 200):
            self.responses.append(httpx.Response(status, json=payload))

        def body(self, index: int = 0) -> dict:
            return json.loads(self.requests[index].content)

        def handler(self, request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return self.responses.pop(0)

    fake = FakeBifrost()
    monkeypatch.setattr(llm, "_transport", httpx.MockTransport(fake.handler))
    return fake


async def test_sends_model_fallbacks_and_virtual_key(bifrost):
    bifrost.reply(completion())

    await llm.chat("extract", MESSAGES, "provider-a/fast", FALLBACKS)

    request = bifrost.requests[0]
    assert str(request.url) == "http://bifrost.test/v1/chat/completions"
    assert request.headers["x-bf-vk"] == "sk-bf-test"
    assert bifrost.body() == {
        "model": "provider-a/fast",
        "messages": MESSAGES,
        "fallbacks": FALLBACKS,
    }


async def test_pipeline_stages_use_exact_match_cache_for_at_most_a_day(bifrost):
    bifrost.reply(completion())

    await llm.chat("adjudicate", MESSAGES, "provider-a/strong", [])

    headers = bifrost.requests[0].headers
    assert headers["x-bf-cache-key"] == "shelflife-adjudicate"
    assert headers["x-bf-cache-type"] == "direct"
    assert headers["x-bf-cache-ttl"] == "24h"


async def test_cache_false_sends_no_cache_headers(bifrost):
    bifrost.reply(completion())

    await llm.chat("extract", MESSAGES, "provider-a/fast", [], cache=False)

    assert "x-bf-cache-key" not in bifrost.requests[0].headers


async def test_returns_routing_cache_usage_and_reported_cost(bifrost):
    routing = {"provider": "provider-b", "model": "fast", "is_fallback": True}
    bifrost.reply(
        completion(
            extra_fields={"routing_info": routing, "cache_debug": {"cache_hit": False}},
            usage={
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
                "cost": {"total_cost": 0.25},
            },
        )
    )

    result = await llm.chat("extract", MESSAGES, "provider-a/fast", FALLBACKS)

    assert result.content == "hi"
    assert result.routing_info == routing
    assert result.cache_debug == {"cache_hit": False}
    assert result.usage == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    assert result.cost_usd == 0.25


async def test_cache_hit_costs_nothing(bifrost):
    bifrost.reply(completion(extra_fields={"cache_debug": {"cache_hit": True}}))

    result = await llm.chat("extract", MESSAGES, "provider-a/fast", [])

    assert result.cost_usd == 0.0


async def test_price_table_prices_the_model_that_actually_served(bifrost, monkeypatch):
    monkeypatch.setattr(
        config,
        "PRICE_TABLE",
        {"provider-b/fast": config.ModelPrice(2.0, 4.0, "2000-01-01", "https://example.test")},
    )
    bifrost.reply(completion(extra_fields={"routing_info": {"provider": "provider-b", "model": "fast"}}))

    result = await llm.chat("extract", MESSAGES, "provider-a/fast", FALLBACKS)

    assert result.cost_usd == pytest.approx((100 * 2.0 + 50 * 4.0) / 1_000_000)


async def test_cost_is_unknown_without_a_reported_cost_or_price(bifrost):
    bifrost.reply(completion())

    result = await llm.chat("extract", MESSAGES, "provider-a/fast", [])

    assert result.cost_usd is None


@pytest.mark.parametrize(
    "content",
    ['{"value": 7}', '```json\n{"value": 7}\n```', 'Here you go: {"value": 7} Thanks!'],
)
async def test_parses_json_replies(bifrost, content):
    bifrost.reply(completion(content))

    result = await llm.chat("extract", MESSAGES, "provider-a/fast", [], json_schema=Answer)

    assert result.parsed == Answer(value=7)
    assert result.attempts == 1
    assert "JSON Schema" in bifrost.body()["messages"][0]["content"]


async def test_invalid_json_is_retried_once_with_the_error(bifrost):
    bifrost.reply(completion('{"value": "not a number"}'))
    bifrost.reply(completion('{"value": 3}'))

    result = await llm.chat("extract", MESSAGES, "provider-a/fast", [], json_schema=Answer)

    assert result.parsed == Answer(value=3)
    assert result.attempts == 2
    assert result.usage["total_tokens"] == 300
    retry_messages = bifrost.body(1)["messages"]
    assert retry_messages[-2]["role"] == "assistant"
    assert "failed validation" in retry_messages[-1]["content"]
    assert "x-bf-cache-key" not in bifrost.requests[1].headers


async def test_second_invalid_reply_raises_validation_error(bifrost):
    bifrost.reply(completion("nope"))
    bifrost.reply(completion("still nope"))

    with pytest.raises(llm.LLMValidationError) as caught:
        await llm.chat("extract", MESSAGES, "provider-a/fast", [], json_schema=Answer)

    assert caught.value.content == "still nope"
    assert caught.value.result.attempts == 2
    assert len(bifrost.requests) == 2


async def test_budget_exceeded_has_its_own_error(bifrost):
    bifrost.reply(
        {"type": "budget_exceeded", "status_code": 402, "error": {"message": "Budget exceeded"}},
        status=402,
    )

    with pytest.raises(llm.BudgetExceededError):
        await llm.chat("extract", MESSAGES, "provider-a/fast", [])


async def test_other_http_errors_include_the_message(bifrost):
    bifrost.reply({"error": {"message": "all providers failed"}}, status=500)

    with pytest.raises(llm.LLMError, match="all providers failed") as caught:
        await llm.chat("extract", MESSAGES, "provider-a/fast", [])

    assert not isinstance(caught.value, llm.BudgetExceededError)
    assert caught.value.status_code == 500


@pytest.mark.parametrize(
    ("status", "error_type", "hint"),
    [
        (401, "virtual_key_required", "set BIFROST_VK"),
        (401, "access_not_found", "BIFROST_VK in .env"),
        (403, "model_blocked", "Allow this model"),
        (403, "access_blocked", "inactive or has expired"),
    ],
)
async def test_governance_errors_say_what_to_fix(bifrost, status, error_type, hint):
    bifrost.reply(
        {"type": error_type, "status_code": status, "error": {"message": "Bifrost said no."}},
        status=status,
    )

    with pytest.raises(llm.LLMError) as caught:
        await llm.chat("extract", MESSAGES, "provider-a/fast", [])

    assert "Bifrost said no. " in str(caught.value)
    assert hint in str(caught.value)


async def test_reported_zero_cost_for_used_tokens_counts_as_unknown(bifrost):
    bifrost.reply(completion(usage={"prompt_tokens": 10, "completion_tokens": 5, "cost": {"total_cost": 0}}))

    result = await llm.chat("extract", MESSAGES, "provider-a/fast", [])

    assert result.cost_usd is None


async def test_served_by_names_the_fallback_that_answered(bifrost):
    bifrost.reply(completion(extra_fields={"routing_info": {"provider": "provider-b", "model": "fast"}}))

    result = await llm.chat("extract", MESSAGES, "provider-a/fast", FALLBACKS)

    assert result.served_by == "provider-b/fast"


async def test_budget_status_reads_the_virtual_key_quota(bifrost):
    bifrost.reply(
        {
            "virtual_key_name": "shelflife",
            "is_active": True,
            "budgets": [
                {"max_limit": 5.0, "current_usage": 0.25, "reset_duration": "1M", "id": "x"}
            ],
        }
    )

    status = await llm.budget_status()

    assert bifrost.requests[0].url.path == "/api/governance/virtual-keys/quota"
    assert bifrost.requests[0].headers["x-bf-vk"] == "sk-bf-test"
    assert status == {
        "configured": True,
        "name": "shelflife",
        "is_active": True,
        "budgets": [{"max_limit": 5.0, "current_usage": 0.25, "reset_duration": "1M"}],
    }


async def test_budget_status_without_a_virtual_key(bifrost, settings):
    settings.bifrost_vk = ""

    assert await llm.budget_status() == {"configured": False, "budgets": []}
    assert bifrost.requests == []


async def test_unconfigured_model_fails_before_any_request(bifrost):
    with pytest.raises(llm.LLMError, match="No model"):
        await llm.chat("extract", MESSAGES, "", [])

    assert bifrost.requests == []


async def test_connection_failure_becomes_llm_error(monkeypatch):
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    monkeypatch.setattr(llm, "_transport", httpx.MockTransport(refuse))

    with pytest.raises(llm.LLMError, match="Could not reach Bifrost"):
        await llm.chat("extract", MESSAGES, "provider-a/fast", [])
