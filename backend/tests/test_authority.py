from __future__ import annotations

import pytest

from app.authority import (
    MAJOR_NEWS,
    OFFICIAL,
    SOCIAL,
    TRADE_PRESS,
    UNKNOWN,
    WIKIPEDIA,
    authority_for,
)


@pytest.mark.parametrize(
    ("domain", "entities", "expected"),
    [
        ("acme.example", ["Acme"], OFFICIAL),
        ("docs.acme.example", ["Acme Cloud"], OFFICIAL),
        ("acme.co.uk", ["Acme"], OFFICIAL),
        ("open-acme.example", ["Open Acme"], OFFICIAL),
        ("irs.gov", [], OFFICIAL),
        ("service.gov.uk", [], OFFICIAL),
        ("incometax.gov.in", [], OFFICIAL),
        ("commission.europa.eu", [], OFFICIAL),
        ("www.reuters.com", [], MAJOR_NEWS),
        ("uk.reuters.com", [], MAJOR_NEWS),
        ("techcrunch.com", [], TRADE_PRESS),
        ("en.wikipedia.org", [], WIKIPEDIA),
        ("someblog.example", ["Acme"], UNKNOWN),
        ("old.reddit.com", [], SOCIAL),
    ],
)
def test_authority_tiers(domain, entities, expected):
    assert authority_for(domain, entities) == expected


@pytest.mark.parametrize(
    ("domain", "entities"),
    [
        pytest.param("acme.medium.com", ["Acme"], id="subdomain-of-a-blog-host"),
        pytest.param("notreuters.com", [], id="lookalike-of-a-news-site"),
        pytest.param("acme-reviews.example", ["Acme"], id="name-only-contained"),
        pytest.param("bo.example", ["Bo Lee"], id="short-first-word"),
        pytest.param("notgov.com", [], id="lookalike-of-government"),
    ],
)
def test_lookalikes_get_no_extra_authority(domain, entities):
    assert authority_for(domain, entities) == UNKNOWN


def test_user_generated_sites_are_never_official():
    assert authority_for("reddit.com", ["Reddit"]) == SOCIAL
