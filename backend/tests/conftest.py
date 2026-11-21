from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Any

import httpx
import pytest

from app import config, llm, search

ANSWER = "Acme Cloud costs $10 per month. Acme was founded in 1999. Bo Lee is the CEO of Acme."
PRICE_CLAIM = "Acme Cloud costs $10 per month."
FOUNDING_CLAIM = "Acme was founded in 1999."
CEO_CLAIM = "Bo Lee is the CEO of Acme."


@pytest.fixture(autouse=True)
def no_retry_waits(monkeypatch):
    """Retries happen instantly in tests."""

    async def instant(seconds):
        return None

    monkeypatch.setattr(search, "_sleep", instant)


@pytest.fixture(autouse=True)
def settings(request, monkeypatch, tmp_path):
    """Isolate unit tests from the real .env. Live tests use the real settings."""
    if request.node.get_closest_marker("live"):
        yield config.get_settings()
        return

    test_settings = config.Settings(
        _env_file=None,
        tavily_api_key="tvly-test",
        bifrost_url="http://bifrost.test",
        bifrost_vk="sk-bf-test",
        model_fast="provider-a/fast",
        model_strong="provider-a/strong",
        model_stale="provider-a/old",
        fallbacks_fast="provider-b/fast, provider-c/fast",
        fallbacks_strong="provider-b/strong",
        max_claims=12,
        tavily_concurrency=5,
        llm_concurrency=4,
        search_cache_ttl_hours=6,
        search_cache_path=tmp_path / "search.sqlite3",
        history_path=tmp_path / "history.sqlite3",
    )
    monkeypatch.setattr(config, "get_settings", lambda: test_settings)
    yield test_settings


def extracted_claim(text: str, source_text: str, category: str, **overrides) -> dict[str, Any]:
    return {
        "text": text,
        "source_text": source_text,
        "span": None,
        "category": category,
        "entities": ["Acme"],
        "time_sensitive": category != "static",
        "search_queries": [],
        **overrides,
    }


class FakeServices:
    """Stand-in for Bifrost and Tavily, preloaded with one stale and one fresh claim."""

    def __init__(self) -> None:
        recent = (date.today() - timedelta(days=3)).isoformat()
        self.extraction: Any = {
            "claims": [
                extracted_claim(
                    PRICE_CLAIM,
                    "Acme Cloud costs $10 per month",
                    "pricing",
                    entities=["Acme Cloud", "Acme"],
                    search_queries=["Acme Cloud monthly price"],
                    official_domains=["https://www.acme.example/"],
                ),
                extracted_claim(FOUNDING_CLAIM, "Acme was founded in 1999", "static"),
                extracted_claim(
                    CEO_CLAIM,
                    "Bo Lee is the CEO of Acme",
                    "leadership_role",
                    search_queries=["Acme CEO"],
                ),
            ]
        }
        self.search_results: dict[str, list[dict]] = {
            "Acme Cloud monthly price": [
                {
                    "title": "Pricing",
                    "url": "https://acme.example/pricing",
                    "content": "Acme Cloud now costs $25 per month.",
                    "score": 0.9,
                    "published_date": recent,
                }
            ],
            "Acme CEO": [
                {
                    "title": "About Acme",
                    "url": "https://acme.example/about",
                    "content": "Bo Lee is the chief executive of Acme.",
                    "score": 0.8,
                    "published_date": recent,
                }
            ],
        }
        self.adjudications: dict[str, Any] = {
            PRICE_CLAIM: {
                "judgements": [
                    {
                        "id": "E1",
                        "stance": "contradicts",
                        "quote": "Acme Cloud now costs $25 per month",
                    }
                ],
                "current_value": "$25 per month",
                "explanation": "The pricing page lists a higher price.",
            },
            CEO_CLAIM: {
                "judgements": [
                    {
                        "id": "E1",
                        "stance": "supports",
                        "quote": "Bo Lee is the chief executive of Acme",
                    }
                ],
                "current_value": "Bo Lee",
                "explanation": "The company site confirms this.",
            },
        }
        self.rewrite: Any = {
            "replacements": [{"claim_id": "c1", "replacement": "Acme Cloud costs $25 per month"}]
        }
        self.extra_fields: dict[str, Any] = {}
        # Full-page text that Tavily Extract returns, by URL. Empty means pages can't be read.
        self.page_contents: dict[str, str] = {}
        self.extract_requests: list[dict] = []
        self.llm_requests: list[dict] = []
        self.search_requests: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "bifrost.test":
            return self._llm(request)
        body = json.loads(request.content)
        if request.url.path == "/extract":
            self.extract_requests.append(body)
            results = [
                {"url": url, "raw_content": self.page_contents[url]}
                for url in body["urls"]
                if url in self.page_contents
            ]
            # Tavily charges only for pages it actually read.
            credits = 1 if results else 0
            return httpx.Response(200, json={"results": results, "usage": {"credits": credits}})
        self.search_requests.append(body)
        results = self.search_results.get(body["query"], [])
        if isinstance(results, httpx.Response):
            return results
        return httpx.Response(200, json={"results": results, "usage": {"credits": 1}})

    def _llm(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.llm_requests.append(body)
        text = "\n".join(message["content"] for message in body["messages"])
        match = re.search(r"<claim>\n(.*?)\n</claim>", text, re.DOTALL)
        if "<passage" in text:
            reply = self.rewrite
        elif match:
            reply = self.adjudications[match.group(1)]
        else:
            reply = self.extraction
        if isinstance(reply, list):  # A queue of replies, one per call.
            reply = reply.pop(0)
        if isinstance(reply, tuple):
            status, payload = reply
            return httpx.Response(status, json=payload)
        content = reply if isinstance(reply, str) else json.dumps(reply)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": content}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
                "extra_fields": self.extra_fields,
            },
        )


@pytest.fixture
def services(monkeypatch) -> FakeServices:
    fake = FakeServices()
    transport = httpx.MockTransport(fake.handler)
    monkeypatch.setattr(llm, "_transport", transport)
    monkeypatch.setattr(search, "_transport", transport)
    return fake
