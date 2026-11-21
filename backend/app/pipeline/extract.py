"""Stage 1: break an answer into self-contained, located claims."""

from __future__ import annotations

import calendar
import re
from collections.abc import Iterator
from datetime import date
from difflib import SequenceMatcher

from pydantic import BaseModel, Field

from app import config, search
from app.models import DERIVED_KINDS, Category, Claim, ClaimKind, TimeFrame
from app.passport import passport_id
from app.pipeline.metrics import MetricsCollector
from app.prompts import load_prompt, neutralise_tag

_DOMAIN = re.compile(r"[a-z0-9-]+(\.[a-z0-9-]+)+")
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+|\n+")
_EXACT_ENOUGH = 0.9
_SAME_SENTENCE = 0.6


class ExtractedClaim(BaseModel):
    ref: str | None = None
    kind: ClaimKind = "fact"
    text: str = Field(min_length=1)
    source_text: str = ""
    span: tuple[int, int] | None = None
    category: Category
    entities: list[str] = []
    time_sensitive: bool
    search_queries: list[str] = []
    official_domains: list[str] = []
    depends_on: list[str] = []
    formula: str | None = None
    number: float | None = None
    time_frame: TimeFrame = "current"
    as_of: str | None = None
    as_of_date: str | None = None


class ExtractionOutput(BaseModel):
    claims: list[ExtractedClaim]


async def extract_claims(
    answer: str,
    question: str | None,
    answer_date: date | None,
    check_date: date,
    metrics: MetricsCollector,
) -> list[Claim]:
    settings = config.get_settings()
    result = await metrics.chat(
        "extract",
        build_messages(answer, question, answer_date, check_date),
        settings.model_fast,
        settings.fallbacks_fast_list,
        json_schema=ExtractionOutput,
    )
    return build_claims(answer, result.parsed.claims, check_date)


def build_messages(
    answer: str, question: str | None, answer_date: date | None, check_date: date
) -> list[dict]:
    parts = [
        f"Today's date: {check_date.isoformat()}. Resolve relative dates such as "
        "'last year' against it unless the answer says when it was written."
    ]
    if answer_date:
        parts.append(
            f"The answer was written on {answer_date.isoformat()}. "
            "Resolve relative dates such as 'last year' or 'in March' against that date. "
            "Claims it presents as the current state are still `current`: the check is "
            "whether they are true today."
        )
    if question:
        parts.append(f"<question>\n{neutralise_tag(question, 'question')}\n</question>")
    parts.append(f"<answer>\n{neutralise_tag(answer, 'answer')}\n</answer>")
    return [
        {"role": "system", "content": load_prompt("extract")},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def period_end(value: str | None) -> date | None:
    """The last day of "2019", "2019-10" or "2019-10-14". Anything else gives None."""
    if not value:
        return None
    match = re.fullmatch(r"(\d{4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?", value.strip())
    if not match:
        return None
    year, month, day = (int(part) if part else None for part in match.groups())
    try:
        if month is None:
            return date(year, 12, 31)
        if day is None:
            return date(year, month, calendar.monthrange(year, month)[1])
        return date(year, month, day)
    except ValueError:
        return None


def _time_frame(item: ExtractedClaim, check_date: date | None) -> tuple[TimeFrame, str | None, date | None]:
    """Keep the model's time frame only when its date is consistent with it."""
    frame = item.time_frame
    as_of = (item.as_of or "").strip()[:80] or None
    as_of_date = period_end(item.as_of_date)
    if frame == "past" and as_of_date and check_date and as_of_date > check_date:
        # "In 2027 the price was..." can't be history yet; judge it as a current claim.
        frame, as_of_date = "current", None
    if frame == "current":
        return "current", None, None
    return frame, as_of, as_of_date


def build_claims(
    answer: str, extracted: list[ExtractedClaim], check_date: date | None = None
) -> list[Claim]:
    """Locate, clean and number claims, in the order they appear in the answer."""
    located: list[tuple[ExtractedClaim, tuple[int, int] | None]] = []
    seen: set[str] = set()
    for item in extracted:
        key = " ".join(item.text.casefold().split())
        if key in seen:
            continue
        seen.add(key)
        # Assumptions aren't in the answer, so they have no place in its text.
        span = None if item.kind == "assumption" else locate_span(
            answer, item.source_text, item.text, item.span
        )
        located.append((item, span))

    located.sort(key=lambda pair: pair[1][0] if pair[1] else len(answer))
    ids = {
        item.ref: f"c{number}" for number, (item, _) in enumerate(located, start=1) if item.ref
    }

    claims = []
    for number, (item, span) in enumerate(located, start=1):
        claim_id = f"c{number}"
        text = item.text.strip()
        queries = [query.strip() for query in item.search_queries if query.strip()]
        derived = item.kind in DERIVED_KINDS
        frame, as_of, as_of_date = _time_frame(item, check_date)
        claims.append(
            Claim(
                id=claim_id,
                text=text,
                span=span,
                category=item.category,
                entities=[entity.strip() for entity in item.entities if entity.strip()],
                time_sensitive=item.time_sensitive,
                search_queries=[] if derived else (queries[: config.MAX_QUERIES_PER_CLAIM] or [text]),
                official_domains=_clean_domains(item.official_domains),
                kind=item.kind,
                depends_on=[ids[ref] for ref in item.depends_on if ref in ids and ids[ref] != claim_id],
                formula=_map_formula(item.formula, ids) if item.kind == "calculation" else None,
                number=item.number,
                passport_id=passport_id(text),
                time_frame=frame,
                as_of=as_of,
                as_of_date=as_of_date,
            )
        )
    return claims


def _map_formula(formula: str | None, ids: dict[str, str]) -> str | None:
    """Rewrite {ref} placeholders as claim ids. Unknown refs make the formula unusable."""
    if not formula:
        return None
    refs = re.findall(r"\{([^{}]+)\}", formula)
    if not refs or any(ref not in ids for ref in refs):
        return None
    return re.sub(r"\{([^{}]+)\}", lambda match: "{" + ids[match.group(1)] + "}", formula)


def locate_span(
    answer: str, source_text: str, claim_text: str, span: tuple[int, int] | None
) -> tuple[int, int] | None:
    """Find where a claim sits in the answer, without trusting the model's offsets."""
    target = source_text.strip() or claim_text.strip()
    if not target:
        return None

    if span and 0 <= span[0] < span[1] <= len(answer):
        if _similarity(answer[span[0] : span[1]], target) >= _EXACT_ENOUGH:
            return span

    start = answer.find(target)
    if start != -1:
        return start, start + len(target)

    # Same words, with different case or spacing.
    pattern = r"\s+".join(re.escape(word) for word in target.split())
    match = re.search(pattern, answer, re.IGNORECASE)
    if match:
        return match.span()

    # Fall back to the sentence that reads most like the claim.
    best_span = None
    best_ratio = 0.0
    for sentence_start, sentence_end in _sentences(answer):
        sentence = answer[sentence_start:sentence_end]
        ratio = max(_similarity(sentence, target), _similarity(sentence, claim_text))
        if ratio > best_ratio:
            best_ratio = ratio
            best_span = (sentence_start, sentence_end)
    return best_span if best_ratio >= _SAME_SENTENCE else None


def _similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, left.casefold().strip(), right.casefold().strip()).ratio()


def _sentences(text: str) -> Iterator[tuple[int, int]]:
    start = 0
    for match in _SENTENCE_BREAK.finditer(text):
        if match.start() > start:
            yield start, match.start()
        start = match.end()
    if start < len(text):
        yield start, len(text)


def _clean_domains(domains: list[str]) -> list[str]:
    cleaned: list[str] = []
    for value in domains:
        value = value.strip().lower()
        domain = search.domain_of(value) if "://" in value else value.removeprefix("www.")
        domain = domain.split("/")[0]
        if _DOMAIN.fullmatch(domain) and domain not in cleaned:
            cleaned.append(domain)
    return cleaned[:2]
