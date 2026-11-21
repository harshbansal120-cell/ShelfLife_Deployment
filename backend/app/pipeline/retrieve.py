"""Stage 3: gather live web sources for a claim."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from app import config, search
from app.authority import OFFICIAL, authority_for
from app.models import CheckContext, Claim
from app.pipeline.metrics import MetricsCollector

NEWS_CATEGORIES = {"leadership_role", "event_status", "product_status"}
OFFICIAL_DOMAIN_CATEGORIES = {"pricing", "version_api"}
# Official pages for these often give thin search snippets, so read the full page.
EXTRACT_CATEGORIES = {"pricing", "version_api", "product_status"}
# Claims whose truth depends on where you are: searched with the context's country.
LOCAL_CATEGORIES = {"pricing", "law_regulation", "product_status"}


@dataclass
class RetrievedSources:
    sources: list[search.SearchResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    all_failed: bool = False


async def retrieve_sources(
    claim: Claim,
    semaphore: asyncio.Semaphore,
    metrics: MetricsCollector,
    deep: bool = False,
    context: CheckContext | None = None,
) -> RetrievedSources:
    """Run the claim's queries in parallel and merge the results."""
    # History is better served by general pages than by recent news.
    topic = "news" if claim.category in NEWS_CATEGORIES and not claim.historical else "general"
    domains = None
    if claim.category in OFFICIAL_DOMAIN_CATEGORIES and claim.official_domains:
        domains = claim.official_domains
    country = context.country if context else None
    local = bool(country) and (claim.kind == "availability" or claim.category in LOCAL_CATEGORIES)

    async def run(query: str) -> search.SearchResponse:
        if local and country.lower() not in query.lower():
            query = f"{query} {country.title()}"
        async with semaphore:
            return await search.search(
                query, topic=topic, deep=deep, include_domains=domains,
                country=country if local else None,
            )

    outcomes = await asyncio.gather(
        *(run(query) for query in claim.search_queries), return_exceptions=True
    )

    results: list[search.SearchResult] = []
    errors: list[str] = []
    for outcome in outcomes:
        if isinstance(outcome, search.SearchError):
            errors.append(str(outcome))
        elif isinstance(outcome, BaseException):
            raise outcome
        else:
            metrics.record_search(outcome)
            results.extend(outcome.results)

    sources = merge_results(results)
    if sources:
        async with semaphore:
            sources = await read_full_pages(claim, sources, metrics)
    return RetrievedSources(
        sources=sources,
        errors=errors,
        all_failed=bool(errors) and len(errors) == len(outcomes),
    )


async def read_full_pages(
    claim: Claim, sources: list[search.SearchResult], metrics: MetricsCollector
) -> list[search.SearchResult]:
    """Replace thin snippets from the entity's own site with passages from the full page.

    A failed extract leaves the snippets as they were.
    """
    if not config.get_settings().use_tavily_extract or claim.category not in EXTRACT_CATEGORIES:
        return sources
    thin = [
        source
        for source in sources
        if len(source.snippet) < config.THIN_SNIPPET_CHARS
        and authority_for(source.domain, claim.entities) == OFFICIAL
    ][: config.MAX_EXTRACT_PAGES_PER_CLAIM]
    if not thin:
        return sources
    try:
        response = await search.extract(
            [source.url for source in thin], query=claim.search_queries[0]
        )
    except search.SearchError:
        return sources
    metrics.record_extract(response)
    updated = []
    for source in sources:
        content = (response.contents.get(source.url) or "").strip()
        if content and len(content) > len(source.snippet):
            source = source.model_copy(
                update={"snippet": content[: config.MAX_SNIPPET_CHARS], "extracted": True}
            )
        updated.append(source)
    return updated


def merge_results(results: list[search.SearchResult]) -> list[search.SearchResult]:
    """Remove duplicate URLs and keep the best-matching sources."""
    ranked = sorted(results, key=lambda item: item.score or 0.0, reverse=True)
    merged: list[search.SearchResult] = []
    seen: set[str] = set()
    for item in ranked:
        canonical = search.canonical_url(item.url)
        if canonical not in seen:
            seen.add(canonical)
            merged.append(item)
    return merged[: config.MAX_SOURCES_PER_CLAIM]
