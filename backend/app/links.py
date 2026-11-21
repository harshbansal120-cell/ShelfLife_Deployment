"""Link rot: do cited pages and evidence pages still say what we relied on?

Only public http(s) addresses are fetched, so a check can't be pointed at the
server's own network.
"""

from __future__ import annotations

import asyncio
import html
import ipaddress
import re
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from app.models import CheckResult
from app.pipeline.adjudicate import verified_quote

TIMEOUT = httpx.Timeout(8.0, connect=4.0)
MAX_REDIRECTS = 4
MAX_LINKS = 40
# Tests and demo mode replace these.
_transport: httpx.AsyncBaseTransport | None = None
_public_only = True
# In demo mode only the simulator's invented sites (ending in this) are visited.
_demo_suffix: str | None = None

_URL = re.compile(r"https?://[^\s<>()\"']+")
_TAGS = re.compile(r"<(script|style)[^>]*>.*?</\1>|<[^>]+>", re.S | re.I)


def urls_in_text(text: str) -> list[str]:
    seen: list[str] = []
    for url in _URL.findall(text):
        url = url.rstrip(".,;:!?]")
        if url not in seen:
            seen.append(url)
    return seen


async def _is_public(host: str) -> bool:
    if not _public_only:
        return True
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global:
            return False
    return True


def page_text(body: str) -> str:
    return " ".join(html.unescape(_TAGS.sub(" ", body)).split())


async def check_url(url: str, quote: str | None = None) -> dict[str, Any]:
    """Classify one link: ok, changed, moved, gone, blocked or error."""
    report: dict[str, Any] = {"url": url, "final_url": url, "http_status": None, "quote": quote}
    current = url
    redirected = False
    async with httpx.AsyncClient(timeout=TIMEOUT, transport=_transport, follow_redirects=False) as client:
        for _ in range(MAX_REDIRECTS + 1):
            parts = urlsplit(current)
            if parts.scheme not in ("http", "https") or not parts.hostname:
                return {**report, "status": "error", "detail": "Not a web address."}
            if _demo_suffix and not parts.hostname.endswith(_demo_suffix):
                return {**report, "status": "error",
                        "detail": f"Only {_demo_suffix} sites are visited in this workspace."}
            if not await _is_public(parts.hostname):
                return {**report, "status": "error", "detail": "Only public web addresses are checked."}
            try:
                response = await client.get(current, headers={"user-agent": "ShelfLife link check"})
            except httpx.HTTPError as exc:
                return {**report, "status": "error", "detail": f"Couldn't connect ({type(exc).__name__})."}
            if response.status_code in (301, 302, 303, 307, 308) and response.headers.get("location"):
                current = urljoin(current, response.headers["location"])
                redirected = True
                continue
            break
    report.update(final_url=current, http_status=response.status_code)
    status = response.status_code
    if status in (404, 410):
        return {**report, "status": "gone", "detail": "The page no longer exists."}
    if status in (401, 403, 429):
        return {**report, "status": "blocked", "detail": "The site refused the check, so it may still be fine."}
    if status >= 400:
        return {**report, "status": "error", "detail": f"The site returned HTTP {status}."}
    if quote and not verified_quote(quote, page_text(response.text)):
        return {**report, "status": "changed", "detail": "The page no longer contains the quoted evidence."}
    if redirected:
        return {**report, "status": "moved", "detail": "The address now redirects elsewhere."}
    return {**report, "status": "ok", "detail": "The page is reachable" + (" and still has the quote." if quote else ".")}


def items_for_check(result: CheckResult) -> list[dict[str, Any]]:
    """The links a check relied on: those in the answer, then each source with its quote."""
    items: list[dict[str, Any]] = [{"url": url, "source": "answer"} for url in urls_in_text(result.answer)]
    seen = {item["url"] for item in items}
    for claim in result.claims:
        for evidence in claim.evidence:
            if evidence.stance != "irrelevant" and evidence.url not in seen:
                seen.add(evidence.url)
                items.append({"url": evidence.url, "quote": evidence.quote, "claim_id": claim.claim.id,
                              "claim_text": claim.claim.text, "source": "evidence"})
    return items


async def check_links(items: list[dict[str, Any]], concurrency: int = 5) -> list[dict[str, Any]]:
    """Check many links at once. Each item has a url and, optionally, a quote and claim_id."""
    slots = asyncio.Semaphore(concurrency)

    async def one(item: dict[str, Any]) -> dict[str, Any]:
        async with slots:
            outcome = await check_url(item["url"], item.get("quote"))
        return {**outcome, "claim_id": item.get("claim_id"), "claim_text": item.get("claim_text"),
                "source": item.get("source", "evidence")}

    return list(await asyncio.gather(*(one(item) for item in items[:MAX_LINKS])))
