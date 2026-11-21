"""Tests for the evaluation tools. All data here is invented."""

from __future__ import annotations

import importlib.util
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

import pytest

from app.evaluation import dataset, matching, metrics, report, runner, tuning
from app.evaluation.dataset import EvalClaim, EvalItem, apply_label
from app.evaluation.metrics import ClaimRecord, ItemRun
from app.pipeline import orchestrator
from app.pipeline.score import DEFAULT_PARAMS, ScoreParams
from conftest import ANSWER, CEO_CLAIM, FOUNDING_CLAIM, PRICE_CLAIM

TODAY = date(2026, 3, 10)
SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def labelled(text: str, gold: str, **overrides) -> EvalClaim:
    values = {
        "text": text,
        "gold": gold,
        "current_value": "new value" if gold == "stale" else None,
        "source_url": None if gold == "static" else "https://acme.example/source",
        "verified_by": "Tester",
        "verified_on": TODAY,
    }
    return EvalClaim(**{**values, **overrides})


def record(gold: str, verdict: str | None, topic: str = "t", item_id: str = "i1") -> ClaimRecord:
    return ClaimRecord(
        item_id=item_id,
        topic=topic,
        gold_text="x",
        gold=gold,
        predicted_text="x" if verdict else None,
        similarity=1.0 if verdict else 0.0,
        verdict=verdict,
        score=None,
        category="pricing" if verdict else None,
        check_date=TODAY.isoformat(),
    )


# --- dataset -----------------------------------------------------------------


def test_items_round_trip_and_keep_extra_fields(tmp_path):
    path = tmp_path / "data.jsonl"
    item = EvalItem(id="a", answer="Text.", claims=[labelled("C.", "fresh")], answer_model="m/x")

    dataset.save_items(path, [item])
    loaded = dataset.load_items(path)

    assert loaded == [item]
    assert loaded[0].model_extra["answer_model"] == "m/x"


def test_missing_dataset_is_empty(tmp_path):
    assert dataset.load_items(tmp_path / "none.jsonl") == []


def test_broken_line_is_reported_with_its_number(tmp_path):
    path = tmp_path / "data.jsonl"
    path.write_text('{"id": "a", "answer": "x"}\n{not json}\n', encoding="utf-8")

    with pytest.raises(dataset.DatasetError, match="line 2"):
        dataset.load_items(path)


@pytest.mark.parametrize(
    ("claim", "problem"),
    [
        (EvalClaim(text="c"), "not labelled"),
        (labelled("c", "fresh", source_url=None), "source URL"),
        (labelled("c", "fresh", source_url="javascript:alert(1)"), "source URL"),
        (labelled("c", "stale", current_value=" "), "current value"),
        (labelled("c", "fresh", verified_by=None), "verified_by"),
        (labelled("c", "fresh", verified_on=None), "verified_on"),
    ],
)
def test_incomplete_labels_are_caught(claim, problem):
    assert any(problem in text for text in dataset.label_problems(claim))


@pytest.mark.parametrize("gold", ["stale", "fresh", "static"])
def test_complete_labels_pass(gold):
    assert dataset.label_problems(labelled("c", gold)) == []


def test_apply_label_records_who_and_when():
    claim = apply_label(
        EvalClaim(text="c"),
        "stale",
        current_value=" $25 ",
        source_url=" https://acme.example/p ",
        labeller="Tester",
        today=TODAY,
    )

    assert (claim.gold, claim.current_value, claim.source_url) == (
        "stale",
        "$25",
        "https://acme.example/p",
    )
    assert (claim.verified_by, claim.verified_on) == ("Tester", TODAY)


def test_apply_label_refuses_a_label_without_a_source():
    with pytest.raises(ValueError, match="source URL"):
        apply_label(
            EvalClaim(text="c"), "fresh", current_value=None, source_url="", labeller="T", today=TODAY
        )


def test_static_label_needs_no_source():
    claim = apply_label(
        EvalClaim(text="c"), "static", current_value=None, source_url=None, labeller="T", today=TODAY
    )
    assert claim.gold == "static"


def test_check_item_excludes_unlabelled_and_warns_about_old_labels():
    item = EvalItem(
        id="a",
        answer="Text.",
        claims=[EvalClaim(text="c"), labelled("d", "fresh", verified_on=date(2026, 1, 1))],
    )

    errors, warnings = dataset.check_item(item, TODAY, max_label_age_days=7)

    assert errors == ["claim 1 not labelled yet"]
    assert len(warnings) == 1 and "claim 2" in warnings[0]


# --- matching ----------------------------------------------------------------


def test_same_claim_in_other_words_matches():
    assert matching.similarity("Acme Cloud costs $10 per month.", "Acme Cloud costs $10 a month") > 0.7


def test_different_numbers_lower_the_match():
    same = matching.similarity("Acme has 40 million users.", "Acme has 40 million users")
    different = matching.similarity("Acme has 40 million users.", "Acme has 90 million users")

    assert different < same * 0.7


def test_each_prediction_is_used_once_best_match_first():
    gold = ["Acme Cloud costs $10 per month.", "Bo Lee is the CEO of Acme."]
    predicted = ["Bo Lee is Acme's CEO.", "Acme Cloud costs $10 per month on Starter.", "Unrelated."]

    matches = matching.match_claims(gold, predicted)

    assert [index for index, _ in matches] == [1, 0]


def test_claims_below_the_threshold_stay_unmatched():
    matches = matching.match_claims(["Acme was founded in 1999."], ["Bo Lee likes tea."])

    assert matches == [(None, 0.0)]


# --- metrics -----------------------------------------------------------------


def test_stale_detection_counts():
    records = [
        record("stale", "stale"),
        record("stale", "fresh"),
        record("stale", None),
        record("fresh", "stale"),
        record("fresh", "fresh"),
        record("static", "stale"),
    ]

    result = metrics.stale_detection(records, {"stale"})

    assert (result["tp"], result["fn"], result["fp"], result["tn"]) == (1, 2, 1, 1)
    assert result["precision"] == pytest.approx(0.5)
    assert result["recall"] == pytest.approx(1 / 3)
    assert result["f1"] == pytest.approx(0.4)


def test_detection_without_predictions_has_no_precision():
    result = metrics.stale_detection([record("stale", "fresh")], {"stale"})

    assert result["precision"] is None
    assert result["f1"] is None


def test_summary_numbers():
    records = [
        record("stale", "stale", topic="a"),
        record("stale", None, topic="a"),
        record("fresh", "fresh", topic="b"),
        record("fresh", "unverified", topic="b"),
        record("static", "not_time_sensitive", topic="b"),
        record("fresh", "stale", item_id="failed"),
    ]
    runs = [
        ItemRun("i1", None, ok=True, latency_ms=2000, cost_usd=0.01, llm_calls=4, tavily_credits=3),
        ItemRun("failed", None, ok=False, error="boom"),
    ]

    summary = metrics.summarise(records, runs)

    assert summary["answers"] == 1 and summary["failed_answers"] == 1
    assert summary["gold_claims"] == 5
    assert summary["extraction_recall"] == pytest.approx(0.8)
    assert summary["false_alarm_rate"] == 0
    assert summary["unverified_rate"] == pytest.approx(1 / 3)
    assert summary["static_handled"] == 1
    assert summary["confusion"]["stale"] == {"stale": 1, "not_extracted": 1}
    assert summary["by_topic"]["a"]["recall"] == pytest.approx(0.5)
    assert summary["avg_latency_ms"] == 2000


def test_lenient_detection_counts_uncertain_as_flagged():
    records = [record("stale", "uncertain"), record("fresh", "fresh")]

    summary = metrics.summarise(records, [ItemRun("i1", None, ok=True)])

    assert summary["stale_strict"]["recall"] == 0
    assert summary["stale_lenient"]["recall"] == 1


def test_cache_hit_rate():
    runs = [ItemRun("a", None, True, llm_calls=4, cache_hits=3), ItemRun("b", None, False)]

    assert metrics.cache_hit_rate(runs) == 0.75


# --- report ------------------------------------------------------------------


def test_report_shows_headline_numbers_and_method():
    records = [record("stale", "stale"), record("fresh", "fresh"), record("static", None)]
    summary = metrics.summarise(records, [ItemRun("i1", None, ok=True, latency_ms=1500)])
    meta = {
        "run_date": "2026-03-10",
        "dataset": "data/eval/stale_answers.jsonl",
        "labels_from": "2026-03-09",
        "labels_to": "2026-03-10",
        "model_fast": "p/fast",
        "model_strong": "p/strong",
        "cache_hit_rate": 0.9,
    }

    text = report.render_markdown(summary, meta)

    assert "| Stale detection F1 | 100% |" in text
    assert "| Bifrost cache hit rate on a second run | 90% |" in text
    assert "| static | 0 | 0 | 0 | 0 | 0 | 0 | 1 |" in text
    assert "1.5 s" in text
    assert "human-labelled" in text


def test_readme_results_are_replaced_between_the_markers():
    readme = f"Intro\n{report.README_START}\nold numbers\n{report.README_END}\nOutro\n"

    updated = report.update_readme(readme, "| Metric | Value |")

    assert updated == f"Intro\n{report.README_START}\n| Metric | Value |\n{report.README_END}\nOutro\n"
    assert report.update_readme(updated, "new").count(report.README_START) == 1


def test_readme_without_markers_is_left_alone():
    with pytest.raises(ValueError, match="markers"):
        report.update_readme("No markers here.", "x")


def test_readme_block_lists_the_headline_numbers():
    summary = metrics.summarise(
        [record("stale", "stale"), record("fresh", "fresh")],
        [ItemRun("i1", None, ok=True, latency_ms=2500, cost_usd=0.002)],
    )
    meta = {"run_date": "2026-03-10", "cache_hit_rate": None}

    block = report.readme_block(summary, meta)

    assert "| Stale detection F1 | 100% |" in block
    assert "| Average time per answer | 2.5 s |" in block
    assert "eval/results.md" in block
    assert "cache hit" not in block


def test_project_readme_has_the_results_markers():
    readme = (Path(__file__).resolve().parents[2] / "README.md").read_text(encoding="utf-8")

    assert readme.count(report.README_START) == 1
    assert readme.count(report.README_END) == 1


# --- runner, against the simulated services -----------------------------------


def acme_item() -> EvalItem:
    return EvalItem(
        id="acme",
        topic="pricing_version",
        answer=ANSWER,
        claims=[
            labelled(PRICE_CLAIM, "stale"),
            labelled(CEO_CLAIM, "fresh"),
            labelled(FOUNDING_CLAIM, "static"),
            labelled("Acme has 3 offices.", "fresh"),
        ],
    )


async def test_runner_records_each_gold_claim(services):
    runs, records = await runner.evaluate([acme_item()])

    assert runs[0].ok and runs[0].llm_calls == 4 and runs[0].extra_predictions == 0
    verdicts = {r.gold_text: r.verdict for r in records}
    assert verdicts == {
        PRICE_CLAIM: "stale",
        CEO_CLAIM: "fresh",
        FOUNDING_CLAIM: "not_time_sensitive",
        "Acme has 3 offices.": None,
    }
    price = next(r for r in records if r.gold_text == PRICE_CLAIM)
    assert price.evidence[0]["stance"] == "contradicts"
    json.dumps([asdict(r) for r in records])


async def test_runner_marks_a_failed_answer(services):
    services.extraction = "not JSON"

    runs, records = await runner.evaluate([acme_item()])

    assert runs[0].ok is False and "extract" in runs[0].error
    assert records == []


async def test_runner_passes_the_cache_setting(monkeypatch):
    seen = {}

    async def run_check(answer, **kwargs):
        seen.update(kwargs)
        raise orchestrator.PipelineError("stop")

    monkeypatch.setattr(orchestrator, "run_check", run_check)

    await runner.evaluate([acme_item()], use_cache=False)

    assert seen["use_cache"] is False


# --- tuning ------------------------------------------------------------------


async def test_rescoring_with_the_default_constants_reproduces_the_run(services):
    _, records = await runner.evaluate([acme_item()])

    rescored = [tuning.rescore(r, DEFAULT_PARAMS) for r in records]

    assert [r.verdict for r in rescored] == [r.verdict for r in records]
    assert [r.score for r in rescored] == [r.score for r in records]


async def test_rescoring_with_other_constants_can_change_verdicts(services):
    _, records = await runner.evaluate([acme_item()])
    ceo = next(r for r in records if r.gold_text == CEO_CLAIM)

    strict = tuning.rescore(ceo, ScoreParams(min_evidence=5))

    assert strict.verdict == "unverified"


def test_sweep_ranks_rows_by_f1():
    records = [
        ClaimRecord("i", None, "x", "stale", "x", 1, "stale", 10, "pricing", "2026-03-10",
                    [{"authority": 1.0, "published_date": "2026-03-01", "stance": "contradicts"}]),
        ClaimRecord("i", None, "y", "fresh", "y", 1, "fresh", 95, "pricing", "2026-03-10",
                    [{"authority": 1.0, "published_date": "2025-09-01", "stance": "supports"}]),
    ]

    rows = tuning.sweep(records, {"half_life_scale": (0.25, 1.0), "uncertain_threshold": (40,)})

    assert len(rows) == 2
    assert rows[0]["f1"] >= (rows[1]["f1"] or 0)
    assert rows[0]["params"].half_life_scale == 1.0


# --- scripts -----------------------------------------------------------------


async def test_build_item_drafts_unlabelled_claims(monkeypatch):
    build = load_script("eval_build")

    async def fake_generate(question):
        return type("Generated", (), {"answer": "Acme costs $10.", "model": "p/old"})()

    async def fake_extract(answer, question, answer_date, check_date, collector):
        return [type("Claim", (), {"text": "Acme costs $10."})()]

    monkeypatch.setattr(build, "generate_stale_answer", fake_generate)
    monkeypatch.setattr(build, "extract_claims", fake_extract)

    item = await build.build_item({"id": "q1", "topic": "pricing_version", "question": "Q?"})

    assert item.answer == "Acme costs $10."
    assert [c.text for c in item.claims] == ["Acme costs $10."]
    assert all(c.gold is None for c in item.claims)
    assert item.model_extra["answer_model"] == "p/old"


def test_label_tool_rechecks_only_old_or_incomplete_labels():
    label = load_script("eval_label")

    assert label.needs_work(EvalClaim(text="c"), TODAY, None) is True
    assert label.needs_work(labelled("c", "fresh"), TODAY, None) is False
    assert label.needs_work(labelled("c", "fresh", verified_on=date(2026, 3, 1)), TODAY, 3) is True
    assert label.needs_work(labelled("c", "static", verified_on=date(2026, 1, 1)), TODAY, 3) is False


def test_question_list_is_well_formed():
    lines = (Path(__file__).resolve().parents[2] / "data/eval/questions.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    rows = [json.loads(line) for line in lines if line.strip()]
    topics = [row["topic"] for row in rows]

    assert 30 <= len(rows) <= 50
    assert len({row["id"] for row in rows}) == len(rows)
    assert topics.count("pricing_version") / len(rows) == pytest.approx(0.4, abs=0.05)
    assert topics.count("leadership_law") / len(rows) == pytest.approx(0.3, abs=0.05)
    assert topics.count("stats_status") / len(rows) == pytest.approx(0.3, abs=0.05)
    assert all(row["question"].endswith("?") for row in rows)
