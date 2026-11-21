from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from app import search

RESULT = {
    "title": "Example page",
    "url": "https://www.example.test/page",
    "content": "Example snippet",
    "score": 0.9,
    "published_date": "Tue, 11 Mar 2025 17:00:00 GMT",
}


@pytest.fixture
def tavily(monkeypatch):
    class FakeTavily:
        def __init__(self):
            self.requests: list[httpx.Request] = []
            self.status = 200
            self.payload: dict = {"results": [RESULT], "usage": {"credits": 1}}

        def body(self, index: int = 0) -> dict:
            return json.loads(self.requests[index].content)

        def handler(self, request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return httpx.Response(self.status, json=self.payload)

    fake = FakeTavily()
    monkeypatch.setattr(search, "_transport", httpx.MockTransport(fake.handler))
    return fake


async def test_basic_search_sets_required_parameters_explicitly(tavily):
    await search.search("example query", topic="news")

    request = tavily.requests[0]
    assert str(request.url) == "https://api.tavily.com/search"
    assert request.headers["authorization"] == "Bearer tvly-test"
    assert tavily.body() == {
        "query": "example query",
        "topic": "news",
        "search_depth": "basic",
        "max_results": 5,
        "include_published_date": True,
        "include_favicon": True,
        "include_usage": True,
    }


async def test_deep_search_uses_advanced_depth(tavily):
    tavily.payload = {"results": []}

    response = await search.search("example query", deep=True)

    assert tavily.body()["search_depth"] == "advanced"
    assert response.credits == 2


async def test_official_domains_are_preferred_not_required(tavily):
    await search.search("example query", include_domains=["example.test"])

    assert tavily.body()["include_domains"] == ["example.test"]
    assert tavily.body()["include_domains_mode"] == "prefer"


async def test_results_are_normalised(tavily):
    response = await search.search("example query")

    assert response.credits == 1
    assert response.cached is False
    result = response.results[0]
    assert result.domain == "example.test"
    assert result.snippet == "Example snippet"
    assert result.published_date == date(2025, 3, 11)


@pytest.mark.parametrize(
    ("favicon", "expected"),
    [
        ("https://example.test/icon.png", "https://example.test/icon.png"),
        ("http://example.test/icon.png", None),
        ("javascript:alert(1)", None),
        (None, None),
    ],
)
async def test_only_https_favicons_are_kept(tavily, favicon, expected):
    tavily.payload["results"] = [{**RESULT, "favicon": favicon}]

    response = await search.search("example query")

    assert response.results[0].favicon == expected


async def test_duplicate_urls_are_removed(tavily):
    tavily.payload["results"] = [
        RESULT,
        {**RESULT, "url": "https://WWW.example.test/page/#section"},
        {**RESULT, "url": "https://www.example.test/other"},
    ]

    response = await search.search("example query")

    assert [item.url for item in response.results] == [
        "https://www.example.test/page",
        "https://www.example.test/other",
    ]


async def test_repeat_search_is_served_from_cache_for_free(tavily):
    await search.search("example query")
    repeat = await search.search("example query")

    assert len(tavily.requests) == 1
    assert repeat.cached is True
    assert repeat.credits == 0
    assert repeat.results[0].published_date == date(2025, 3, 11)


async def test_different_parameters_do_not_share_a_cache_entry(tavily):
    await search.search("example query", topic="general")
    await search.search("example query", topic="news")

    assert len(tavily.requests) == 2


async def test_expired_cache_entry_triggers_a_new_search(tavily, monkeypatch):
    now = 1_000_000.0
    monkeypatch.setattr(search.time, "time", lambda: now)
    await search.search("example query")

    now += 6 * 3600
    await search.search("example query")

    assert len(tavily.requests) == 2


async def test_failed_search_raises_and_is_not_cached(tavily):
    tavily.status = 401
    tavily.payload = {"detail": {"error": "Unauthorized"}}

    with pytest.raises(search.SearchError, match="Unauthorized"):
        await search.search("example query")

    tavily.status = 200
    tavily.payload = {"results": [RESULT], "usage": {"credits": 1}}
    response = await search.search("example query")
    assert response.cached is False


async def test_missing_api_key_fails_before_any_request(tavily, settings):
    settings.tavily_api_key = ""

    with pytest.raises(search.SearchError, match="TAVILY_API_KEY"):
        await search.search("example query")

    assert tavily.requests == []


async def test_rate_limit_is_retried(monkeypatch):
    statuses = [429, 429, 200]
    waits = []

    def handler(request):
        status = statuses.pop(0)
        if status == 429:
            return httpx.Response(429, headers={"retry-after": "2"}, json={"detail": {"error": "slow"}})
        return httpx.Response(200, json={"results": [RESULT], "usage": {"credits": 1}})

    async def record(seconds):
        waits.append(seconds)

    monkeypatch.setattr(search, "_transport", httpx.MockTransport(handler))
    monkeypatch.setattr(search, "_sleep", record)

    response = await search.search("example query")

    assert len(response.results) == 1
    assert waits == [2.0, 2.0]


async def test_persistent_rate_limit_explains_what_to_do(monkeypatch):
    monkeypatch.setattr(
        search, "_transport", httpx.MockTransport(lambda r: httpx.Response(429, json={}))
    )

    with pytest.raises(search.SearchError, match="rate-limiting"):
        await search.search("example query")


async def test_rate_limited_health_check_is_a_warning_not_a_failure(monkeypatch):
    monkeypatch.setattr(
        search, "_transport", httpx.MockTransport(lambda r: httpx.Response(429, json={}))
    )

    status = await search.health()

    assert status["ok"] is True and status["rate_limited"] is True


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("_Update on Monday:_ __New model__ is out.", "Update on Monday: New model is out."),
        ("**Bold** and snake_case stay readable", "Bold and snake_case stay readable"),
        ("# Pricing\nStarter costs $25", "Pricing Starter costs $25"),
    ],
)
def test_snippets_lose_markdown_marks(raw, expected):
    assert search.clean_text(raw) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Tue, 11 Mar 2025 17:00:00 GMT", date(2025, 3, 11)),
        ("2025-03-11", date(2025, 3, 11)),
        ("2025-03-11T17:00:00Z", date(2025, 3, 11)),
        ("not a date", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_published_date(value, expected):
    assert search.parse_published_date(value) == expected
