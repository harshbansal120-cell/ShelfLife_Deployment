"""Stage 6: produce a corrected answer that changes only the stale claims.

The model only writes a short replacement for each stale passage. Code splices the
replacements into the original text by character offset, so everything else stays
word for word, and adds the citation markers and "(could not verify)" flags itself.

Claims whose passages overlap are corrected together. "Version 3.13, launched on
October 7, 2024" holds two claims (the version and its release date); when the
version is out of date, its date usually is too, and both must change in one
consistent edit rather than one of them being dropped into a footnote.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from pydantic import BaseModel

from app import config, llm
from app.models import AnswerEdit, Citation, ClaimResult, Evidence, Rewrite
from app.pipeline.metrics import MetricsCollector
from app.prompts import load_prompt, neutralise_tag

COULD_NOT_VERIFY = " (could not verify)"
OUT_OF_DATE = " (out of date)"
FLAGGED_VERDICTS = ("unverified", "error")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_CITATION_MARKER = re.compile(r"\[\d+\]")


class Replacement(BaseModel):
    claim_id: str
    replacement: str


class RewriteOutput(BaseModel):
    replacements: list[Replacement]


@dataclass
class _Change:
    result: ClaimResult
    kind: str  # "stale" or "flag"

    @property
    def has_value(self) -> bool:
        return self.kind == "stale" and bool(self.result.current_value)

    @property
    def drops(self) -> bool:
        """A detail of a stale value that couldn't be confirmed for the new value."""
        return self.kind == "flag" and self.result.coupled_to is not None


@dataclass
class _Group:
    """Changes whose passages overlap, so they are edited as one passage."""

    changes: list[_Change] = field(default_factory=list)
    start: int = 0
    end: int = 0

    @property
    def key(self) -> str:
        return self.changes[0].result.claim.id

    @property
    def needs_model(self) -> bool:
        return any(change.has_value for change in self.changes)


def _valid_span(answer: str, result: ClaimResult) -> bool:
    span = result.claim.span
    return bool(span) and 0 <= span[0] < span[1] <= len(answer)


def _numbers(text: str) -> set[str]:
    return {match.replace(",", "") for match in _NUMBER.findall(text)}


def validate_replacement(before: str, replacement: str, current_value: str | list[str]) -> bool:
    """Accept only a drop-in replacement that states the current values and nothing new."""
    values = [current_value] if isinstance(current_value, str) else current_value
    text = replacement.strip()
    if not text or "\n" in text or text == before.strip():
        return False
    if _CITATION_MARKER.search(text):
        return False
    if len(text) > max(3 * len(before), len(before) + sum(len(v) for v in values) + 40):
        return False
    new_numbers = _numbers(text)
    value_numbers = [_numbers(value) for value in values]
    # No numbers may appear that neither the original nor a current value contains.
    if not new_numbers <= _numbers(before).union(*value_numbers):
        return False
    # Each current value with numbers has to be stated with at least one of them.
    return all(not numbers or numbers & new_numbers for numbers in value_numbers)


def best_source(result: ClaimResult) -> Evidence | None:
    """The source to cite for a correction: the heaviest one that contradicts the claim."""
    contradicting = [item for item in result.evidence if item.stance == "contradicts"]
    return max(contradicting, key=lambda item: item.weight, default=None)


def _changes(answer: str, results: list[ClaimResult]) -> tuple[list[_Group], list[_Change]]:
    """Group the changes placed in the text, and list those that become end notes."""
    changes = []
    for result in results:
        if result.verdict == "stale":
            changes.append(_Change(result, "stale"))
        elif result.verdict in FLAGGED_VERDICTS and result.claim.category != "static":
            changes.append(_Change(result, "flag"))

    placed = sorted(
        (change for change in changes if _valid_span(answer, change.result)),
        key=lambda change: change.result.claim.span,
    )
    notes = [change for change in changes if not _valid_span(answer, change.result)]
    groups: list[_Group] = []
    for change in placed:
        start, end = change.result.claim.span
        if groups and start < groups[-1].end:
            groups[-1].changes.append(change)
            groups[-1].end = max(groups[-1].end, end)
        else:
            groups.append(_Group([change], start, end))
    return groups, notes


def _fallback(before: str, group: _Group) -> str:
    """Without a model replacement: swap each old value for its new one where the
    passage states it word for word, and say "now ..." for the rest."""
    text = before
    pending: list[str] = []
    for change in group.changes:
        result = change.result
        if change.has_value:
            old = result.change.old_value if result.change else None
            if old and old in text and len(group.changes) > 1:
                text = text.replace(old, result.current_value, 1)
            else:
                pending.append(f"now {result.current_value}")
        elif change.kind == "stale":
            pending.append("out of date")
        else:
            pending.append("could not verify")
    if len(group.changes) == 1 and pending:
        return f"{text} ({pending[0]})"
    return f"{text} ({'; '.join(pending)})" if pending else text


def build_rewrite(
    answer: str, results: list[ClaimResult], replacements: dict[str, str]
) -> Rewrite:
    groups, notes = _changes(answer, results)
    citations: dict[str, Citation] = {}

    def cite(result: ClaimResult) -> int | None:
        source = best_source(result)
        if source is None:
            return None
        if source.url not in citations:
            citations[source.url] = Citation(
                number=len(citations) + 1,
                url=source.url,
                title=source.title,
                domain=source.domain,
                published_date=source.published_date,
            )
        return citations[source.url].number

    edits: list[AnswerEdit] = []
    for group in groups:
        before = answer[group.start : group.end]
        stale = [change for change in group.changes if change.kind == "stale"]
        numbers = list(dict.fromkeys(n for c in stale if (n := cite(c.result)) is not None))
        if not any(change.has_value for change in group.changes):
            kind, after = "flag", before + (OUT_OF_DATE if stale else COULD_NOT_VERIFY)
        else:
            kind = "replace"
            after = replacements.get(group.key) or _fallback(before, group)
            # Don't double the sentence's full stop when the passage ends just before it.
            if after.endswith(".") and answer[group.end : group.end + 1] == ".":
                after = after[:-1]
            # A detail the model kept unchanged still gets its flag.
            if group.key in replacements and any(
                change.kind == "flag" and not change.drops for change in group.changes
            ):
                after += COULD_NOT_VERIFY
        if numbers:
            after += " " + "".join(f"[{number}]" for number in numbers)
        edits.append(AnswerEdit(
            claim_id=group.key, kind=kind, start=group.start, end=group.end,
            before=before, after=after, citation=numbers[0] if numbers else None,
            claim_ids=[change.result.claim.id for change in group.changes], citations=numbers,
        ))

    note_changes = sorted(
        notes,
        key=lambda change: (0, change.result.claim.span[0])
        if _valid_span(answer, change.result)
        else (1, 0),
    )
    for change in note_changes:
        result = change.result
        citation = None
        if change.kind == "flag":
            text = f"Could not verify: {result.claim.text}"
        elif result.current_value:
            citation = cite(result)
            text = f"Out of date: {result.claim.text} Sources now say: {result.current_value}."
        else:
            citation = cite(result)
            text = f"Out of date: {result.claim.text}"
        if citation is not None:
            text += f" [{citation}]"
        edits.append(AnswerEdit(
            claim_id=result.claim.id, kind="note", start=None, end=None,
            before="", after=text, citation=citation,
            claim_ids=[result.claim.id], citations=[citation] if citation else [],
        ))

    pieces = []
    cursor = 0
    for edit in edits:
        if edit.kind == "note":
            continue
        pieces += [answer[cursor : edit.start], edit.after]
        cursor = edit.end
    pieces.append(answer[cursor:])
    corrected = "".join(pieces)
    note_lines = [edit.after for edit in edits if edit.kind == "note"]
    if note_lines:
        corrected = corrected.rstrip() + "\n\n" + "\n".join(note_lines)

    return Rewrite(
        corrected_answer=corrected, edits=edits, citations=list(citations.values())
    )


def _fact_line(change: _Change) -> str:
    result = change.result
    claim = result.checked_as or result.claim.text
    if change.has_value:
        stated = result.change.old_value if result.change and result.change.old_value else None
        line = f"fact: {claim}"
        if stated:
            line += f" | stated: {stated}"
        if result.claim.historical:
            # Correct the value for that time and keep the answer's time framing.
            when = result.claim.as_of or "that time"
            return f"{line} | value at that time ({when}): {result.current_value}"
        return f"{line} | now: {result.current_value}"
    if change.drops:
        return f"fact: {claim} | now: unknown for the current value, so remove this detail"
    return f"fact: {claim} | now: keep unchanged"


def build_messages(answer: str, groups: list[_Group], check_date: date) -> list[dict]:
    parts = [
        f"Today's date: {check_date.isoformat()}",
        f"<answer>\n{neutralise_tag(answer, 'answer')}\n</answer>",
    ]
    for group in groups:
        lines = [f"original: {answer[group.start : group.end]}"]
        lines += [_fact_line(change) for change in group.changes]
        body = neutralise_tag(neutralise_tag("\n".join(lines), "passage"), "answer")
        parts.append(f'<passage id="{group.key}">\n{body}\n</passage>')
    return [
        {"role": "system", "content": load_prompt("rewrite")},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def _accept(answer: str, group: _Group, replacement: str) -> bool:
    before = answer[group.start : group.end]
    values = [change.result.current_value for change in group.changes if change.has_value]
    if not validate_replacement(before, replacement, values):
        return False
    # A dropped detail's old numbers must actually be gone.
    for change in group.changes:
        if change.drops:
            own = _numbers(answer[slice(*change.result.claim.span)]) - _numbers(
                " ".join(values)
            )
            if own & _numbers(replacement):
                return False
    return True


async def rewrite_answer(
    answer: str, results: list[ClaimResult], check_date: date, metrics: MetricsCollector
) -> Rewrite:
    """Write the corrected answer. Model problems fall back to plain "(now X)" edits."""
    groups, _ = _changes(answer, results)
    targets = [group for group in groups if group.needs_model]
    replacements: dict[str, str] = {}
    if targets:
        settings = config.get_settings()
        try:
            response = await metrics.chat(
                "rewrite",
                build_messages(answer, targets, check_date),
                settings.model_strong,
                settings.fallbacks_strong_list,
                json_schema=RewriteOutput,
            )
        except llm.LLMError:
            response = None
        if response is not None:
            by_key = {group.key: group for group in targets}
            for item in response.parsed.replacements:
                group = by_key.get(item.claim_id)
                if group is None or item.claim_id in replacements:
                    continue
                if _accept(answer, group, item.replacement):
                    replacements[item.claim_id] = item.replacement.strip()
    return build_rewrite(answer, results, replacements)
