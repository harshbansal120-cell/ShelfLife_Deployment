"""Group sources that are not independent: one owner's pages, or copies of one story.

Three sites repeating the same press release are one confirmation, not three.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.authority import owner_label
from app.search import SearchResult

SAME_STORY = 0.8


def _comparable(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.casefold()).split())[:400]


def group_sources(sources: list[SearchResult]) -> list[str]:
    """Return a group id per source. Sources sharing an id are not independent."""
    parent = list(range(len(sources)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    texts = [_comparable(source.snippet) for source in sources]
    owners = [owner_label(source.domain) for source in sources]
    for i in range(len(sources)):
        for j in range(i + 1, len(sources)):
            same_owner = owners[i] == owners[j]
            same_story = bool(texts[i]) and (
                SequenceMatcher(None, texts[i], texts[j]).ratio() >= SAME_STORY
            )
            if same_owner or same_story:
                parent[find(j)] = find(i)
    return [f"g{find(index) + 1}" for index in range(len(sources))]
