"""Settings, scoring constants, cache policy and the LLM price table."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BACKEND_DIR.parent


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=(),
    )

    tavily_api_key: str = ""
    # 127.0.0.1, not localhost: on Windows, localhost adds ~0.5s per new connection,
    # which would distort the latency metrics.
    bifrost_url: str = "http://127.0.0.1:8080"
    bifrost_vk: str = ""

    model_fast: str = ""
    model_strong: str = ""
    model_stale: str = ""
    fallbacks_fast: str = ""
    fallbacks_strong: str = ""

    max_claims: int = Field(default=12, gt=0)
    # Kept low because Tavily rate-limits bursts of searches.
    tavily_concurrency: int = Field(default=3, gt=0)
    llm_concurrency: int = Field(default=4, gt=0)
    # Read full official pages with Tavily Extract when search snippets are thin.
    use_tavily_extract: bool = True
    # Run against a built-in simulator with invented data: no keys, no credits.
    demo_mode: bool = False
    # Optional: POST a JSON alert here when a check finds stale claims.
    alert_webhook_url: str = ""
    # Only for reading and enabling Bifrost's cache plugin from the System page.
    bifrost_setup_token: str = ""
    bifrost_admin_user: str = ""
    bifrost_admin_password: str = ""
    # Tavily results must stay short-lived so the cache can't make us stale. 0 disables it.
    search_cache_ttl_hours: float = Field(default=6, ge=0, le=6)
    search_cache_path: Path = BACKEND_DIR / ".cache" / "search.sqlite3"
    # Finished checks, for history, the watchlist and affected answers.
    history_path: Path = BACKEND_DIR / ".cache" / "history.sqlite3"
    # Browser origins allowed to call the API.
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        return _split_csv(self.cors_origins)

    @property
    def fallbacks_fast_list(self) -> list[str]:
        return _split_csv(self.fallbacks_fast)

    @property
    def fallbacks_strong_list(self) -> list[str]:
        return _split_csv(self.fallbacks_strong)

    def missing_required(self) -> list[str]:
        """Names of the settings the pipeline can't run without."""
        required = {
            "TAVILY_API_KEY": self.tavily_api_key,
            "MODEL_FAST": self.model_fast,
            "MODEL_STRONG": self.model_strong,
        }
        return [name for name, value in required.items() if not value]


@lru_cache
def get_settings() -> Settings:
    return Settings()


# --- Freshness scoring (tune with the eval set) ------------------------------

HALF_LIFE_DAYS: dict[str, int] = {
    "pricing": 90,
    "version_api": 120,
    "product_status": 120,
    "statistic": 180,
    "leadership_role": 365,
    "law_regulation": 540,
    "event_status": 30,
}

MIN_EVIDENCE = 0.15
FRESH_THRESHOLD = 70
UNCERTAIN_THRESHOLD = 40
CONFIDENCE_SCALE = 0.8
CONFIDENCE_MEDIUM = 0.4
CONFIDENCE_HIGH = 0.7
# Recency for sources with no date. Official pages are usually kept current.
UNDATED_RECENCY_OFFICIAL = 0.7
UNDATED_RECENCY_OTHER = 0.35

# --- Evidence limits ---------------------------------------------------------

MAX_QUERIES_PER_CLAIM = 2
MAX_SOURCES_PER_CLAIM = 8
MAX_SNIPPET_CHARS = 1500
MAX_QUOTE_WORDS = 25
# Tavily Extract: which snippets count as thin, and how many pages to read per claim.
THIN_SNIPPET_CHARS = 400
MAX_EXTRACT_PAGES_PER_CLAIM = 2

# --- API limits --------------------------------------------------------------

MAX_ANSWER_CHARS = 20_000
MAX_QUESTION_CHARS = 2_000
# Each check spends LLM and Tavily credits, so only a few may run at once.
MAX_ACTIVE_CHECKS = 5
MAX_STORED_CHECKS = 100
SSE_HEARTBEAT_SECONDS = 15.0


# --- Bifrost cache policy ----------------------------------------------------


@dataclass(frozen=True)
class CachePolicy:
    ttl: str = "24h"
    cache_type: Literal["direct", "semantic"] = "direct"


# Pipeline stages use exact matching. Two answers that differ only in a number
# ("$20" vs "$25") embed almost identically, so a semantic hit could return claims
# or verdicts for the wrong text, and could also bypass the evidence hash.
# The demo generator is safe to match semantically: a reworded question can
# reasonably reuse the same answer.
CACHE_POLICIES: dict[str, CachePolicy] = {
    "generate_stale": CachePolicy(cache_type="semantic"),
}
DEFAULT_CACHE_POLICY = CachePolicy()


# --- LLM prices --------------------------------------------------------------


@dataclass(frozen=True)
class ModelPrice:
    input_per_mtok: float
    output_per_mtok: float
    copied_on: str
    source_url: str


# Used only when Bifrost doesn't report a cost. A human fills this in from the
# provider's pricing page, keyed by "provider/model". Never fill it from memory.
PRICE_TABLE: dict[str, ModelPrice] = {}
