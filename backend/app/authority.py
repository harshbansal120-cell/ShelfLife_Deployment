"""Rate how authoritative a source's domain is for a given claim."""

from __future__ import annotations

import re
from collections.abc import Iterable

OFFICIAL = 1.0
MAJOR_NEWS = 0.8
TRADE_PRESS = 0.7
WIKIPEDIA = 0.6
UNKNOWN = 0.4
SOCIAL = 0.2

MAJOR_NEWS_DOMAINS = {
    "apnews.com",
    "afp.com",
    "bbc.co.uk",
    "bbc.com",
    "bloomberg.com",
    "cnbc.com",
    "economist.com",
    "ft.com",
    "nytimes.com",
    "reuters.com",
    "theguardian.com",
    "washingtonpost.com",
    "wsj.com",
}

TRADE_PRESS_DOMAINS = {
    "arstechnica.com",
    "cnet.com",
    "engadget.com",
    "infoq.com",
    "spectrum.ieee.org",
    "technologyreview.com",
    "techcrunch.com",
    "theregister.com",
    "theverge.com",
    "venturebeat.com",
    "wired.com",
    "zdnet.com",
}

# User-generated content. These never count as an entity's own site, because anyone
# can post there: a Reddit thread is not an official statement by Reddit.
SOCIAL_DOMAINS = {
    "discord.com",
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "news.ycombinator.com",
    "quora.com",
    "reddit.com",
    "stackexchange.com",
    "stackoverflow.com",
    "threads.net",
    "tiktok.com",
    "twitter.com",
    "x.com",
    "youtube.com",
}

_GOVERNMENT = re.compile(r"(^|\.)(gov(\.[a-z]{2})?|mil|europa\.eu|gouv\.fr|gc\.ca)$")
_SECOND_LEVEL_LABELS = {"ac", "co", "com", "edu", "gov", "net", "org"}
_MIN_BRAND_WORD_LENGTH = 4


def authority_for(domain: str, entities: Iterable[str] = ()) -> float:
    """Return the authority tier for `domain`, given the claim's entities."""
    domain = domain.lower().strip(".").removeprefix("www.")
    if _GOVERNMENT.search(domain):
        return OFFICIAL
    if _in_list(domain, SOCIAL_DOMAINS):
        return SOCIAL
    if _in_list(domain, {"wikipedia.org"}):
        return WIKIPEDIA
    if _is_entity_site(domain, entities):
        return OFFICIAL
    if _in_list(domain, MAJOR_NEWS_DOMAINS):
        return MAJOR_NEWS
    if _in_list(domain, TRADE_PRESS_DOMAINS):
        return TRADE_PRESS
    return UNKNOWN


def _in_list(domain: str, known: set[str]) -> bool:
    return any(domain == item or domain.endswith(f".{item}") for item in known)


def _registrable_label(domain: str) -> str:
    """Return the name a site registered: 'acme' for docs.acme.com or acme.co.uk.

    Only this label counts, so acme.medium.com isn't mistaken for Acme's own site.
    """
    labels = domain.split(".")
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in _SECOND_LEVEL_LABELS:
        return labels[-3]
    return labels[-2] if len(labels) >= 2 else domain


owner_label = _registrable_label


def _entity_keys(entity: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", entity.casefold())
    if not words:
        return set()
    keys = {"".join(words)}
    # "Acme Cloud" should still match acme.com.
    if len(words[0]) >= _MIN_BRAND_WORD_LENGTH:
        keys.add(words[0])
    return keys


def _is_entity_site(domain: str, entities: Iterable[str]) -> bool:
    label = _registrable_label(domain).replace("-", "")
    return any(label in _entity_keys(entity) for entity in entities)
