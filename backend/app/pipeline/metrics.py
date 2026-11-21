"""Collect cost, token, cache and fallback figures for one check."""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel

from app import llm, search
from app.models import LLMCallInfo, Metrics


def call_info(result: llm.LLMResult) -> LLMCallInfo:
    routing = result.routing_info
    primary = None
    if routing.get("primary_provider") and routing.get("primary_model"):
        primary = f"{routing['primary_provider']}/{routing['primary_model']}"
    return LLMCallInfo(
        served_by=result.served_by,
        is_fallback=bool(routing.get("is_fallback")),
        primary_model=primary,
        cache_hit=bool(result.cache_debug.get("cache_hit")),
        cache_hit_type=result.cache_debug.get("hit_type"),
    )


class MetricsCollector:
    def __init__(self, use_cache: bool = True) -> None:
        # Applies to every call this check makes, so stages need not pass it along.
        self.use_cache = use_cache
        self._started = time.perf_counter()
        self.llm_calls = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.cost_usd = 0.0
        self.unpriced_calls = 0
        self.cache_hits = 0
        self.tavily_credits = 0
        self.fallback_events: list[dict[str, Any]] = []
        self.per_stage: dict[str, dict[str, Any]] = {}

    async def chat(
        self,
        stage: str,
        messages: list[dict],
        model: str,
        fallbacks: list[str],
        json_schema: type[BaseModel] | None = None,
        cache: bool = True,
    ) -> llm.LLMResult:
        """Call the LLM and record the outcome, including failed validation attempts."""
        cache = cache and self.use_cache
        try:
            result = await llm.chat(stage, messages, model, fallbacks, json_schema, cache)
        except llm.LLMValidationError as exc:
            if exc.result is not None:
                self.record_llm(stage, exc.result)
            raise
        self.record_llm(stage, result)
        return result

    def record_llm(self, stage: str, result: llm.LLMResult) -> None:
        tokens_in = result.usage.get("prompt_tokens", 0)
        tokens_out = result.usage.get("completion_tokens", 0)
        cache_hit = bool(result.cache_debug.get("cache_hit"))

        self.llm_calls += result.attempts
        self.tokens_in += tokens_in
        self.tokens_out += tokens_out
        self.cache_hits += int(cache_hit)
        if result.cost_usd is None:
            self.unpriced_calls += 1
        else:
            self.cost_usd += result.cost_usd

        stage_metrics = self.per_stage.setdefault(
            stage,
            {
                "calls": 0,
                "tokens_in": 0,
                "tokens_out": 0,
                "cost_usd": 0.0,
                "cache_hits": 0,
                "latency_ms": 0,
            },
        )
        stage_metrics["calls"] += result.attempts
        stage_metrics["tokens_in"] += tokens_in
        stage_metrics["tokens_out"] += tokens_out
        stage_metrics["cost_usd"] += result.cost_usd or 0.0
        stage_metrics["cache_hits"] += int(cache_hit)
        stage_metrics["latency_ms"] += result.latency_ms

        routing = result.routing_info
        if routing.get("is_fallback"):
            self.fallback_events.append(
                {
                    "stage": stage,
                    "provider": routing.get("provider"),
                    "model": routing.get("model"),
                    "primary_provider": routing.get("primary_provider"),
                    "primary_model": routing.get("primary_model"),
                }
            )

    def record_search(self, response: search.SearchResponse) -> None:
        self.tavily_credits += response.credits
        stage_metrics = self.per_stage.setdefault(
            "retrieve", {"searches": 0, "cached_searches": 0, "credits": 0}
        )
        stage_metrics["searches"] += 1
        stage_metrics["cached_searches"] += int(response.cached)
        stage_metrics["credits"] += response.credits

    def record_extract(self, response: search.ExtractResponse) -> None:
        self.tavily_credits += response.credits
        stage_metrics = self.per_stage.setdefault(
            "retrieve", {"searches": 0, "cached_searches": 0, "credits": 0}
        )
        stage_metrics["pages_read"] = stage_metrics.get("pages_read", 0) + len(response.contents)
        stage_metrics["credits"] += response.credits

    def snapshot(self) -> Metrics:
        return Metrics(
            llm_calls=self.llm_calls,
            tokens_in=self.tokens_in,
            tokens_out=self.tokens_out,
            cost_usd=self.cost_usd,
            cache_hits=self.cache_hits,
            fallback_events=self.fallback_events,
            tavily_credits=self.tavily_credits,
            latency_ms=round((time.perf_counter() - self._started) * 1000),
            per_stage=self.per_stage,
            unpriced_calls=self.unpriced_calls,
        )
