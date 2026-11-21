from __future__ import annotations

import pytest
from pydantic import ValidationError

from app import config


def test_env_example_loads_with_empty_values_left_empty(monkeypatch):
    for name in ("MODEL_STRONG", "MODEL_STALE", "FALLBACKS_FAST", "BIFROST_VK"):
        monkeypatch.delenv(name, raising=False)

    settings = config.Settings(_env_file=config.ROOT_DIR / ".env.example")

    assert settings.model_strong == ""
    assert settings.model_stale == ""
    assert settings.fallbacks_fast_list == []
    assert settings.bifrost_vk == ""
    assert settings.max_claims == 12


def test_fallback_lists_are_split_and_trimmed(settings):
    assert settings.fallbacks_fast_list == ["provider-b/fast", "provider-c/fast"]


def test_missing_required_names_empty_settings():
    settings = config.Settings(
        _env_file=None, tavily_api_key="", model_fast="a/b", model_strong=""
    )
    assert settings.missing_required() == ["TAVILY_API_KEY", "MODEL_STRONG"]


def test_search_cache_ttl_cannot_exceed_six_hours():
    with pytest.raises(ValidationError):
        config.Settings(_env_file=None, search_cache_ttl_hours=7)
