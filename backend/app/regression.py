"""Regression tests for AI answers: ask saved questions again and check the answers.

A test fails when the model's fresh answer contains a stale claim, or leaves out a
phrase the test says it must include. Runs are kept, so you can see when a
model's answers started to go wrong.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, Field, StringConstraints

from app import config, history, llm, workspace
from app.models import QuestionText
from app.pipeline.orchestrator import BUDGET_MESSAGE, PipelineError, run_check
from app.prompts import load_prompt, neutralise_tag


class TestRequest(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    question: QuestionText
    model: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] | None = None
    must_include: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]] = Field(
        default_factory=list, max_length=10
    )


def problems_in(answer: str, verdicts: list[tuple[str, str, str | None]], must_include: list[str]) -> list[str]:
    """Why a run failed. Each verdict is (claim text, verdict, current value)."""
    problems = [
        f"Stale: {text}" + (f" (now {current})" if current else "")
        for text, verdict, current in verdicts
        if verdict == "stale"
    ]
    lowered = answer.casefold()
    problems += [f"Missing: \"{phrase}\"" for phrase in must_include if phrase.casefold() not in lowered]
    return problems


async def run_test(test: dict[str, Any]) -> dict[str, Any]:
    settings = config.get_settings()
    model = test.get("model") or settings.model_stale or settings.model_fast
    messages = [
        {"role": "system", "content": load_prompt("regression_answer")},
        {"role": "user", "content": f"<question>\n{neutralise_tag(test['question'], 'question')}\n</question>"},
    ]
    try:
        reply = await llm.chat("regression", messages, model, settings.fallbacks_fast_list, cache=False)
    except llm.BudgetExceededError as exc:
        raise PipelineError(BUDGET_MESSAGE, "budget_exceeded") from exc
    except llm.LLMError as exc:
        raise PipelineError(f"The model under test failed: {exc}", "generation_failed") from exc
    answer = reply.content.strip()
    if not answer:
        raise PipelineError("The model under test returned an empty answer.", "generation_failed")

    result = await run_check(answer, question=test["question"])
    history.store().save(result)
    problems = problems_in(
        answer,
        [(item.claim.text, item.verdict, item.current_value) for item in result.claims],
        test["must_include"],
    )
    return workspace.save_run(
        test["id"], passed=not problems, check_id=result.id, answer=answer,
        model=reply.served_by or model, problems=problems,
    )
