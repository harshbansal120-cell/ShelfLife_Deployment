"""Freshness policies: how fast each kind of fact goes stale for a particular app.

A fact has no single shelf life. A student reading about the history of a language
doesn't need the release list re-checked every week; a production deployment needs
to hear about a deprecated endpoint at once. A policy sets, per category:

- the half-life used to score evidence age (shorter means sources go stale faster),
- an optional fixed re-check interval, so a claim is re-verified at least that often
  even if its evidence still looks recent, and
- which stale categories are serious enough to hold the whole answer back.

Presets cover common kinds of app. Apps can save their own, and choose a default.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Annotated, Any

from pydantic import BaseModel, Field, StringConstraints, field_validator

from app import workspace
from app.config import HALF_LIFE_DAYS

CATEGORIES = tuple(HALF_LIFE_DAYS)
DEFAULT_POLICY_ID = "balanced"
_MAX_DAYS = 3650

CATEGORY_LABELS = {
    "pricing": "pricing",
    "version_api": "version and API",
    "product_status": "product status",
    "statistic": "statistic",
    "leadership_role": "leadership",
    "law_regulation": "law and regulation",
    "event_status": "current event",
}


class PolicyRequest(BaseModel):
    """A policy's settings, as an app saves them."""

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] = ""
    # Days for a source's weight to halve, per category. Missing categories use the default.
    half_life_days: dict[str, int] = Field(default_factory=dict)
    # Re-verify a claim at least this often, per category, whatever its evidence says.
    recheck_days: dict[str, int] = Field(default_factory=dict)
    # A stale claim in any of these categories means the answer should be held back.
    withhold_categories: list[str] = Field(default_factory=list)
    # Hold the answer back when at least this share of checked claims is stale.
    withhold_ratio: float = Field(default=0.5, gt=0, le=1)

    @field_validator("half_life_days", "recheck_days")
    @classmethod
    def known_categories(cls, value: dict[str, int]) -> dict[str, int]:
        unknown = set(value) - set(CATEGORIES)
        if unknown:
            raise ValueError(f"unknown categories: {', '.join(sorted(unknown))}")
        if any(not 1 <= days <= _MAX_DAYS for days in value.values()):
            raise ValueError(f"days must be between 1 and {_MAX_DAYS}")
        return value

    @field_validator("withhold_categories")
    @classmethod
    def known_withhold(cls, value: list[str]) -> list[str]:
        unknown = set(value) - set(CATEGORIES)
        if unknown:
            raise ValueError(f"unknown categories: {', '.join(sorted(unknown))}")
        return sorted(set(value), key=CATEGORIES.index)



class FreshnessPolicy(PolicyRequest):
    id: str
    preset: bool = False

    def half_life(self, category: str) -> int:
        return self.half_life_days.get(category, HALF_LIFE_DAYS.get(category, 120))

    def half_lives(self) -> dict[str, int]:
        return {category: self.half_life(category) for category in CATEGORIES}

    def recheck_date(self, category: str, check_date: date) -> date | None:
        days = self.recheck_days.get(category)
        return check_date + timedelta(days=days) if days else None


PRESETS: list[FreshnessPolicy] = [
    FreshnessPolicy(
        id="balanced",
        name="Balanced",
        description="General-purpose assistants. Each kind of fact ages at its usual rate.",
        preset=True,
    ),
    FreshnessPolicy(
        id="developer",
        name="Developer assistant",
        description="API versions and code compatibility are re-checked often; a stale API claim holds the answer back.",
        preset=True,
        half_life_days={"version_api": 30, "product_status": 60},
        recheck_days={"version_api": 7, "product_status": 14},
        withhold_categories=["version_api"],
    ),
    FreshnessPolicy(
        id="production_api",
        name="Production API",
        description="Deployed integrations: deprecations and outages matter at once, so versions are re-verified daily.",
        preset=True,
        half_life_days={"version_api": 7, "product_status": 14, "pricing": 30},
        recheck_days={"version_api": 1, "product_status": 1, "pricing": 7},
        withhold_categories=["version_api", "product_status"],
        withhold_ratio=0.25,
    ),
    FreshnessPolicy(
        id="business",
        name="Business intelligence",
        description="Leadership is monitored daily and financial figures often; stale prices or figures hold the answer back.",
        preset=True,
        half_life_days={"leadership_role": 30, "statistic": 30, "pricing": 30, "event_status": 7},
        recheck_days={"leadership_role": 1, "statistic": 7, "pricing": 7, "event_status": 1},
        withhold_categories=["pricing", "statistic", "leadership_role"],
    ),
    FreshnessPolicy(
        id="research",
        name="Research assistant",
        description="Historical and settled facts are monitored lightly; recent figures and findings still get regular checks.",
        preset=True,
        half_life_days={
            "pricing": 270, "version_api": 360, "product_status": 360, "statistic": 90,
            "leadership_role": 1095, "law_regulation": 1620, "event_status": 90,
        },
        recheck_days={"statistic": 30},
        withhold_ratio=0.75,
    ),
]
_PRESET_IDS = {policy.id for policy in PRESETS}

SCHEMA = """
CREATE TABLE IF NOT EXISTS policies (
    id TEXT PRIMARY KEY, policy TEXT NOT NULL, updated_at TEXT NOT NULL);
"""


def _custom() -> list[FreshnessPolicy]:
    rows = workspace.query("SELECT policy FROM policies ORDER BY updated_at", schema=SCHEMA)
    return [FreshnessPolicy.model_validate_json(row["policy"]) for row in rows]


def list_policies() -> list[FreshnessPolicy]:
    return [*PRESETS, *_custom()]


def get_policy(policy_id: str | None) -> FreshnessPolicy | None:
    if not policy_id:
        return None
    return next((policy for policy in list_policies() if policy.id == policy_id), None)


def default_policy_id() -> str:
    chosen = workspace.get_setting("default_policy", DEFAULT_POLICY_ID)
    return chosen if get_policy(chosen) else DEFAULT_POLICY_ID


def resolve(policy_id: str | None) -> FreshnessPolicy:
    """The policy to use: the one asked for, else the app's default."""
    return get_policy(policy_id) or get_policy(default_policy_id()) or PRESETS[0]


def set_default(policy_id: str) -> None:
    if get_policy(policy_id) is None:
        raise KeyError(policy_id)
    workspace.set_setting("default_policy", policy_id)


def save_policy(request: PolicyRequest, policy_id: str | None = None) -> FreshnessPolicy:
    if policy_id in _PRESET_IDS:
        raise PermissionError("Presets can't be changed. Save a copy instead.")
    policy = FreshnessPolicy(id=policy_id or f"p-{workspace.new_id()}", preset=False, **request.model_dump())
    workspace.execute(
        "INSERT OR REPLACE INTO policies VALUES (?, ?, ?)",
        (policy.id, policy.model_dump_json(), workspace.now()),
        schema=SCHEMA,
    )
    return policy


def delete_policy(policy_id: str) -> None:
    if policy_id in _PRESET_IDS:
        raise PermissionError("Presets can't be deleted.")
    workspace.execute("DELETE FROM policies WHERE id = ?", (policy_id,), schema=SCHEMA)
    if workspace.get_setting("default_policy", DEFAULT_POLICY_ID) == policy_id:
        workspace.set_setting("default_policy", DEFAULT_POLICY_ID)


def summary(policy: FreshnessPolicy) -> dict[str, Any]:
    """The policy with every category filled in, for the API."""
    return {
        **json.loads(policy.model_dump_json()),
        "effective_half_life_days": policy.half_lives(),
        "category_labels": CATEGORY_LABELS,
    }
