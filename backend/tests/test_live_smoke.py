"""Smoke tests against the real services. Run with: uv run pytest -m live

Each test skips itself if the setting it needs isn't in .env.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from app import config, llm, search

pytestmark = pytest.mark.live


class Echo(BaseModel):
    word: str


async def test_bifrost_is_reachable():
    status = await llm.health()
    assert status["ok"], status


async def test_chat_through_bifrost():
    settings = config.get_settings()
    if not settings.model_fast:
        pytest.skip("MODEL_FAST is not set")

    result = await llm.chat(
        "smoke",
        [{"role": "user", "content": "Reply with the single word: ok"}],
        settings.model_fast,
        settings.fallbacks_fast_list,
        cache=False,
    )

    assert result.content.strip()
    assert result.usage["total_tokens"] > 0


async def test_structured_chat_through_bifrost():
    settings = config.get_settings()
    if not settings.model_fast:
        pytest.skip("MODEL_FAST is not set")

    result = await llm.chat(
        "smoke",
        [{"role": "user", "content": 'Return {"word": "ok"}'}],
        settings.model_fast,
        settings.fallbacks_fast_list,
        json_schema=Echo,
        cache=False,
    )

    assert isinstance(result.parsed, Echo)


async def test_tavily_search():
    if not config.get_settings().tavily_api_key:
        pytest.skip("TAVILY_API_KEY is not set")

    response = await search.search("Tavily search API documentation")

    assert response.results
    assert response.results[0].url.startswith("http")
