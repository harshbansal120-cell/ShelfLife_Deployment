"""Demo helper: get a from-memory answer from an older model, ready to be checked."""

from __future__ import annotations

from app import config, llm
from app.models import GenerateStaleResponse
from app.pipeline.orchestrator import BUDGET_MESSAGE, PipelineError
from app.prompts import load_prompt, neutralise_tag


async def generate_stale_answer(question: str) -> GenerateStaleResponse:
    settings = config.get_settings()
    if not settings.model_stale:
        raise PipelineError("Missing settings in .env: MODEL_STALE.", "not_configured")

    messages = [
        {"role": "system", "content": load_prompt("stale_answer")},
        {
            "role": "user",
            "content": f"<question>\n{neutralise_tag(question, 'question')}\n</question>",
        },
    ]
    try:
        result = await llm.chat(
            "generate_stale", messages, settings.model_stale, settings.fallbacks_fast_list
        )
    except llm.BudgetExceededError as exc:
        raise PipelineError(BUDGET_MESSAGE, "budget_exceeded") from exc
    except llm.LLMError as exc:
        raise PipelineError(f"Could not generate an answer: {exc}", "generation_failed") from exc

    answer = result.content.strip()
    if not answer:
        raise PipelineError("The model returned an empty answer.", "generation_failed")

    routing = result.routing_info
    provider = routing.get("provider")
    model = routing.get("model")
    return GenerateStaleResponse(
        question=question,
        answer=answer,
        model=f"{provider}/{model}" if provider and model else settings.model_stale,
        is_fallback=bool(routing.get("is_fallback")),
        cache_hit=bool(result.cache_debug.get("cache_hit")),
        cost_usd=result.cost_usd,
        latency_ms=result.latency_ms,
    )
