"""API and pipeline data models."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints, field_validator

from app.config import MAX_ANSWER_CHARS, MAX_QUESTION_CHARS

AnswerText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_ANSWER_CHARS)
]
QuestionText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_QUESTION_CHARS)
]

Category = Literal[
    "pricing",
    "version_api",
    "product_status",
    "statistic",
    "leadership_role",
    "law_regulation",
    "event_status",
    "static",
]
Verdict = Literal["fresh", "uncertain", "stale", "unverified", "not_time_sensitive", "error"]
Stance = Literal["supports", "contradicts", "irrelevant"]
ChangeType = Literal[
    "value_changed", "superseded", "deprecated", "discontinued", "renamed", "unclear"
]
# fact: stated in the answer. assumption: unstated, but a conclusion relies on it.
# calculation: a figure worked out from other claims. recommendation: a conclusion or advice.
# api_usage: a library call or code pattern. availability: whether something can be had, where.
ClaimKind = Literal[
    "fact", "assumption", "calculation", "recommendation", "api_usage", "availability"
]
DERIVED_KINDS = ("calculation", "recommendation")
# When a claim applies. current: the answer presents it as how things are now.
# past: how things were at a stated time ("in 2019", "at launch"), which later changes
# can't make wrong. future: something planned, scheduled or expected.
TimeFrame = Literal["current", "past", "future"]

# Country names Tavily accepts for its country option (lowercase).
TAVILY_COUNTRIES = (
    "australia", "brazil", "canada", "france", "germany", "india", "indonesia", "italy",
    "japan", "mexico", "netherlands", "singapore", "south africa", "south korea", "spain",
    "united arab emirates", "united kingdom", "united states",
)


class CheckContext(BaseModel):
    """Who the answer is for. A claim can be true in general but wrong for this context."""

    country: str | None = None
    currency: str | None = None
    edition: str | None = None
    environment: str | None = None

    @field_validator("country", mode="before")
    @classmethod
    def known_country(cls, value: object) -> object:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        country = str(value).strip().lower()
        if country not in TAVILY_COUNTRIES:
            raise ValueError(f"country must be one of: {', '.join(TAVILY_COUNTRIES)}")
        return country

    @field_validator("currency", "edition", "environment", mode="before")
    @classmethod
    def blank_is_none(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()[:120]
            return value or None
        return value

    def lines(self) -> list[str]:
        labels = {
            "country": "Country",
            "currency": "Currency",
            "edition": "Product plan or edition",
            "environment": "Software environment",
        }
        return [
            f"{label}: {getattr(self, name).title() if name == 'country' else getattr(self, name)}"
            for name, label in labels.items()
            if getattr(self, name)
        ]

    def is_empty(self) -> bool:
        return not self.lines()


class Claim(BaseModel):
    id: str
    text: str
    span: tuple[int, int] | None
    category: Category
    entities: list[str]
    time_sensitive: bool
    search_queries: list[str]
    # A hint for search only. It never affects a source's authority score.
    official_domains: list[str] = []
    kind: ClaimKind = "fact"
    # Ids of the claims this one relies on.
    depends_on: list[str] = []
    # For calculations: arithmetic over other claims, such as "{c2} * 10".
    formula: str | None = None
    # The main number the claim states, if it has one.
    number: float | None = None
    # Stable id for the same claim across checks: its verification record.
    passport_id: str | None = None
    # The timeline the claim belongs to, read from the whole question and answer.
    time_frame: TimeFrame = "current"
    # The time it describes as the answer puts it ("October 2019"), and that period's last day.
    as_of: str | None = None
    as_of_date: date | None = None

    @property
    def historical(self) -> bool:
        return self.time_frame == "past"


class Evidence(BaseModel):
    id: str
    url: str
    title: str
    domain: str
    snippet: str
    published_date: date | None
    authority: float
    recency: float
    weight: float
    stance: Stance
    quote: str | None
    favicon: str | None = None
    # Sources with the same group are not independent; only one per stance counts.
    group: str | None = None
    counted: bool = True
    # True when the snippet came from reading the full page with Tavily Extract.
    extracted: bool = False


class ScoreBreakdown(BaseModel):
    supporting_weight: float
    contradicting_weight: float
    agreement: float | None
    best_recency: float
    half_life_days: int
    independent_sources: int = 0


class LLMCallInfo(BaseModel):
    """How Bifrost served one LLM call."""

    served_by: str | None
    is_fallback: bool
    primary_model: str | None
    cache_hit: bool
    cache_hit_type: str | None


class ChangeInfo(BaseModel):
    """What changed between the answer and current sources."""

    change_type: ChangeType
    old_value: str | None
    new_value: str
    as_of: date | None
    source_url: str | None


class RecalcInput(BaseModel):
    claim_id: str
    stated: float | None
    current: float | None


class Recalculation(BaseModel):
    """A figure worked out again, in code, from the current values of its inputs."""

    formula: str
    stated: float | None
    recomputed: float | None
    inputs: list[RecalcInput]


class DecisionInfo(BaseModel):
    """Whether a recommendation still holds now that facts it relied on changed.

    This is the model's judgement, labelled as such in the app.
    """

    holds: Literal["yes", "no", "unclear"]
    reason: str
    revised: str | None
    judged_by: str | None


class Guard(BaseModel):
    """What an app should do with the answer: show it, warn, or hold it back."""

    action: Literal["show", "show_with_warning", "withhold"]
    reason: str


class ClaimResult(BaseModel):
    claim: Claim
    verdict: Verdict
    freshness_score: int | None
    confidence: float
    current_value: str | None
    explanation: str
    evidence: list[Evidence]
    score_breakdown: ScoreBreakdown | None = None
    # The adjudication call for this claim, when one was made.
    llm: LLMCallInfo | None = None
    # For fresh and uncertain claims: when the verdict would change as sources age.
    recheck_by: date | None = None
    change: ChangeInfo | None = None
    # Stale claims this one relies on, directly or through other claims.
    affected_by: list[str] = []
    recalculation: Recalculation | None = None
    decision: DecisionInfo | None = None
    # Set when the claim may be true in general but not for the given context.
    context_note: str | None = None
    # Set when this claim is a detail of another claim's value (such as the release
    # date of "the latest version") and that value turned out to be stale: the detail
    # was re-checked for the current value, and this is the claim as it was checked.
    coupled_to: str | None = None
    checked_as: str | None = None


class Metrics(BaseModel):
    llm_calls: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    cache_hits: int
    fallback_events: list[dict]
    tavily_credits: int
    latency_ms: int
    per_stage: dict[str, dict]
    # Calls with no known cost, so cost_usd is a lower bound when this isn't 0.
    unpriced_calls: int = 0


class Citation(BaseModel):
    number: int
    url: str
    title: str
    domain: str
    published_date: date | None


class AnswerEdit(BaseModel):
    """One change in the corrected answer, in the original answer's character offsets.

    kind: "replace" swaps a stale passage, "flag" adds a note after a passage, and
    "note" adds a line at the end for a claim that couldn't be placed in the text.
    """

    claim_id: str
    kind: Literal["replace", "flag", "note"]
    start: int | None
    end: int | None
    before: str
    after: str
    citation: int | None
    # Every claim this edit corrects. Claims whose passages overlap, such as a version
    # and the release date written next to it, are corrected together in one edit.
    claim_ids: list[str] = []
    citations: list[int] = []


class Rewrite(BaseModel):
    corrected_answer: str
    edits: list[AnswerEdit]
    citations: list[Citation]


class CheckResult(BaseModel):
    id: str
    answer: str
    question: str | None
    check_date: date
    claims: list[ClaimResult]
    answer_score: int | None
    verdict_counts: dict[str, int]
    corrected_answer: str | None
    edits: list[AnswerEdit]
    metrics: Metrics
    citations: list[Citation] = []
    # The earliest re-check date of any claim.
    recheck_by: date | None = None
    checked_at: datetime | None = None
    guard: Guard | None = None
    context: CheckContext | None = None
    profile_id: str | None = None
    profile_version: int | None = None
    # The freshness policy the check was scored with.
    policy_id: str | None = None
    # Set when the check was started by the autonomous agent rather than a person.
    trigger: str | None = None


class CheckRequest(BaseModel):
    answer: AnswerText
    question: QuestionText | None = None
    answer_date: date | None = None
    deep: bool = False
    # Off forces every LLM call to reach a provider, e.g. to demo a fallback.
    use_cache: bool = True
    context: CheckContext | None = None
    # A saved context profile. Its context is used, and later changes to it are tracked.
    profile_id: str | None = None
    # A freshness policy: how fast each kind of fact goes stale for this app.
    policy_id: str | None = None

    @field_validator("question", mode="before")
    @classmethod
    def blank_question_is_none(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value


class CheckCreated(BaseModel):
    check_id: str


class GenerateStaleRequest(BaseModel):
    question: QuestionText


class GenerateStaleResponse(BaseModel):
    question: str
    answer: str
    model: str
    is_fallback: bool
    cache_hit: bool
    cost_usd: float | None
    latency_ms: int
