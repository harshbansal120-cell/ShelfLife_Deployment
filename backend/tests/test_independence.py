from datetime import date

from app.pipeline.independence import group_sources
from app.pipeline.score import SourceInput, score_claim
from app.search import SearchResult

CHECK_DATE = date(2026, 1, 10)


def source(url: str, snippet: str) -> SearchResult:
    return SearchResult(
        url=url, title="t", domain=url.split("/")[2], snippet=snippet,
        published_date=date(2026, 1, 1), score=0.5,
    )


def test_same_owner_and_copied_stories_share_a_group():
    story = "Acme announced today that its Starter plan now costs $25 per month for all users"
    groups = group_sources([
        source("https://acme.example/pricing", "Acme Cloud costs $25 per month."),
        source("https://docs.acme.example/plans", "Plans and limits for teams."),
        source("https://news-a.example/x", story + "."),
        source("https://news-b.example/y", story + "!"),
        source("https://blog.example/z", "A different view on cloud pricing in general."),
    ])

    assert groups[0] == groups[1]
    assert groups[2] == groups[3]
    assert len(set(groups)) == 3


def test_sources_in_one_group_count_once_per_stance():
    day = date(2026, 1, 9)
    copies = [SourceInput(1.0, day, "contradicts", "g1")] * 3
    independent = [SourceInput(1.0, day, "contradicts", f"g{i}") for i in range(3)]

    grouped = score_claim(copies, "pricing", CHECK_DATE)
    separate = score_claim(independent, "pricing", CHECK_DATE)

    assert grouped.independent_sources == 1
    assert [item.counted for item in grouped.sources] == [True, False, False]
    assert grouped.confidence < separate.confidence
    assert separate.independent_sources == 3
