"""Tavily client. Every web search in ShelfLife goes through search().

Results are kept in a small on-disk TTL cache so repeated CLI runs and demo
re-runs don't spend credits. The cache is capped at 6 hours in config.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sqlite3
import time
from contextlib import closing
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

import httpx
from pydantic import BaseModel

from app import config

TAVILY_URL = "https://api.tavily.com"
REQUEST_TIMEOUT = httpx.Timeout(30.0, connect=5.0)
HEALTH_TIMEOUT = httpx.Timeout(5.0)
CREDITS_BY_DEPTH = {"basic": 1, "advanced": 2}
# Rate limits and brief server errors are retried, waiting as long as Tavily asks.
RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_RETRIES = 2
MAX_RETRY_WAIT_SECONDS = 10.0
# Tests replace this so retries don't really wait.
_sleep = asyncio.sleep

_MARKDOWN_EMPHASIS = re.compile(r"(?<![\w])[_*]+|[_*]+(?![\w])")
_MARKDOWN_HEADING = re.compile(r"(^|\n)\s*#{1,6}\s+")

# Tests replace this with httpx.MockTransport.
_transport: httpx.AsyncBaseTransport | None = None

Topic = Literal["general", "news", "finance"]


class SearchError(Exception):
    """A Tavily request failed."""


class SearchResult(BaseModel):
    url: str
    title: str
    domain: str
    snippet: str
    published_date: date | None
    score: float | None
    favicon: str | None = None
    extracted: bool = False


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
    credits: int
    cached: bool = False


class ExtractResponse(BaseModel):
    # Page text by URL. With a query, Tavily returns the most relevant passages.
    contents: dict[str, str]
    credits: int
    cached: bool = False


class SearchCache:
    def __init__(self, path: Path, ttl_seconds: float):
        self.path = Path(path)
        self.ttl_seconds = ttl_seconds

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.execute(
            "CREATE TABLE IF NOT EXISTS searches "
            "(key TEXT PRIMARY KEY, stored_at REAL NOT NULL, payload TEXT NOT NULL)"
        )
        return connection

    def get(self, key: str) -> str | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT stored_at, payload FROM searches WHERE key = ?", (key,)
            ).fetchone()
        if row is None or time.time() - row[0] >= self.ttl_seconds:
            return None
        return row[1]

    def set(self, key: str, payload: str) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT OR REPLACE INTO searches (key, stored_at, payload) VALUES (?, ?, ?)",
                (key, time.time(), payload),
            )


async def search(
    query: str,
    *,
    topic: Topic = "general",
    deep: bool = False,
    max_results: int = 5,
    include_domains: list[str] | None = None,
    country: str | None = None,
) -> SearchResponse:
    """Run one Tavily search. Cached responses report zero credits."""
    settings = config.get_settings()
    if not settings.tavily_api_key:
        raise SearchError("TAVILY_API_KEY is not set.")

    depth = "advanced" if deep else "basic"
    body: dict[str, Any] = {
        "query": query,
        "topic": topic,
        "search_depth": depth,
        "max_results": max_results,
        "include_published_date": True,
        "include_favicon": True,
        "include_usage": True,
    }
    if include_domains:
        body["include_domains"] = include_domains
        body["include_domains_mode"] = "prefer"
    # Tavily only accepts a country for general searches.
    if country and topic == "general":
        body["country"] = country

    cache = SearchCache(settings.search_cache_path, settings.search_cache_ttl_hours * 3600)
    cache_key = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    stored = cache.get(cache_key)
    if stored is not None:
        return SearchResponse.model_validate_json(stored).model_copy(
            update={"cached": True, "credits": 0}
        )

    data = await _post("/search", body, settings.tavily_api_key)
    credits = (data.get("usage") or {}).get("credits")
    result = SearchResponse(
        query=query,
        results=_parse_results(data.get("results") or []),
        credits=credits if isinstance(credits, int) else CREDITS_BY_DEPTH[depth],
    )
    cache.set(cache_key, result.model_dump_json())
    return result


async def extract(urls: list[str], query: str | None = None) -> ExtractResponse:
    """Read full pages with Tavily Extract. Cached like searches."""
    settings = config.get_settings()
    if not settings.tavily_api_key:
        raise SearchError("TAVILY_API_KEY is not set.")
    body: dict[str, Any] = {
        "urls": urls[:20],
        "extract_depth": "basic",
        "format": "text",
        "include_usage": True,
    }
    if query:
        body["query"] = query
        body["chunks_per_source"] = 3

    cache = SearchCache(settings.search_cache_path, settings.search_cache_ttl_hours * 3600)
    cache_key = "extract:" + hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    stored = cache.get(cache_key)
    if stored is not None:
        return ExtractResponse.model_validate_json(stored).model_copy(
            update={"cached": True, "credits": 0}
        )

    data = await _post("/extract", body, settings.tavily_api_key)
    contents = {
        item["url"]: clean_text(item["raw_content"])
        for item in data.get("results") or []
        if isinstance(item, dict) and item.get("url") and isinstance(item.get("raw_content"), str)
    }
    credits = (data.get("usage") or {}).get("credits")
    result = ExtractResponse(contents=contents, credits=credits if isinstance(credits, int) else 0)
    cache.set(cache_key, result.model_dump_json())
    return result


async def health() -> dict[str, Any]:
    """Check Tavily's reachability and the API key using the usage endpoint."""
    api_key = config.get_settings().tavily_api_key
    if not api_key:
        return {"ok": False, "detail": "TAVILY_API_KEY is not set"}
    try:
        async with httpx.AsyncClient(timeout=HEALTH_TIMEOUT, transport=_transport) as client:
            response = await client.get(f"{TAVILY_URL}/usage", headers=_auth(api_key))
    except httpx.HTTPError as exc:
        return {"ok": False, "detail": f"unreachable ({type(exc).__name__})"}
    if response.status_code == 429:
        # Rate limited: the key works and Tavily is up, it just wants fewer requests.
        return {"ok": True, "detail": "rate limited", "rate_limited": True}
    if response.status_code != 200:
        return {"ok": False, "detail": f"HTTP {response.status_code}: {_error_text(response)}"}
    try:
        key_usage = response.json().get("key") or {}
    except (ValueError, AttributeError):
        key_usage = {}
    return {
        "ok": True,
        "detail": "reachable",
        "credits_used": key_usage.get("usage"),
        "credits_limit": key_usage.get("limit"),
    }


def _retry_wait(attempt: int, retry_after: str | None) -> float:
    try:
        wait = float(retry_after) if retry_after else 1.5 * 2**attempt
    except ValueError:
        wait = 1.5 * 2**attempt
    return min(max(wait, 0.0), MAX_RETRY_WAIT_SECONDS)


async def _post(path: str, body: dict[str, Any], api_key: str) -> dict[str, Any]:
    """POST to Tavily, retrying rate limits and brief failures, and return the JSON."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, transport=_transport) as client:
                response = await client.post(f"{TAVILY_URL}{path}", json=body, headers=_auth(api_key))
        except httpx.HTTPError as exc:
            if attempt == MAX_RETRIES:
                raise SearchError(f"Could not reach Tavily ({type(exc).__name__}).") from exc
            await _sleep(_retry_wait(attempt, None))
            continue
        if response.status_code in RETRY_STATUSES and attempt < MAX_RETRIES:
            await _sleep(_retry_wait(attempt, response.headers.get("retry-after")))
            continue
        if response.status_code == 429:
            raise SearchError(
                "Tavily is rate-limiting requests. Wait a minute, or lower TAVILY_CONCURRENCY."
            )
        if response.status_code != 200:
            raise SearchError(f"Tavily returned HTTP {response.status_code}: {_error_text(response)}")
        try:
            return response.json()
        except ValueError as exc:
            raise SearchError("Tavily returned a response that isn't JSON.") from exc
    raise SearchError("Tavily could not be reached.")


def clean_text(text: str) -> str:
    """Remove Markdown emphasis and heading marks that search snippets often carry."""
    text = _MARKDOWN_HEADING.sub(r"\1", text)
    text = _MARKDOWN_EMPHASIS.sub("", text)
    return " ".join(text.split())


def _auth(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def _error_text(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        return response.text[:300]
    if isinstance(detail, dict):
        detail = detail.get("error")
    return str(detail or response.text[:300])


def _parse_results(raw_results: list[dict[str, Any]]) -> list[SearchResult]:
    results: list[SearchResult] = []
    seen: set[str] = set()
    for raw in raw_results:
        url = raw.get("url")
        if not url:
            continue
        canonical = canonical_url(url)
        if canonical in seen:
            continue
        seen.add(canonical)
        results.append(
            SearchResult(
                url=url,
                title=raw.get("title") or "",
                domain=domain_of(url),
                snippet=clean_text(raw.get("content") or ""),
                published_date=parse_published_date(raw.get("published_date")),
                score=raw.get("score"),
                favicon=_safe_favicon(raw.get("favicon")),
            )
        )
    return results


def _safe_favicon(value: Any) -> str | None:
    """Keep only https icon URLs, since the browser will load them directly."""
    return value if isinstance(value, str) and value.startswith("https://") else None


def canonical_url(url: str) -> str:
    """Normalise a URL for duplicate detection."""
    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def domain_of(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host.removeprefix("www.")


def parse_published_date(value: Any) -> date | None:
    """Parse Tavily's date, e.g. 'Tue, 11 Mar 2025 17:00:00 GMT' or an ISO date."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        return parsedate_to_datetime(text).date()
    except (TypeError, ValueError, IndexError):
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None
