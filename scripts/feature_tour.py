"""Run every ShelfLife feature against a running backend and print pass or fail.

Demo mode (DEMO_MODE=true in .env) is free and checks exact results,
because the simulator's invented data is known in advance. Against real Bifrost
and Tavily it only checks that each feature works and returns the right shape,
since current facts can't be known in advance, and it spends credits, so it
needs --allow-spend.

Run from backend/ while the API is up:

    uv run python ../scripts/feature_tour.py
    uv run python ../scripts/feature_tour.py --api http://127.0.0.1:8000 --allow-spend
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

import httpx

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = ROOT / "data" / "eval" / "questions.jsonl"


class Tour:
    def __init__(self, api: str, demo: bool) -> None:
        self.client = httpx.Client(base_url=api.rstrip("/"), timeout=180)
        self.demo = demo
        self.passed = 0
        self.failed: list[str] = []
        self.skipped: list[str] = []
        self.cleanup: list[Callable[[], Any]] = []

    def step(self, name: str, run: Callable[[], str | None]) -> None:
        start = time.monotonic()
        try:
            note = run()
        except AssertionError as exc:
            self.failed.append(name)
            print(f"  FAIL  {name}: {exc or 'assertion failed'}")
            return
        except httpx.HTTPError as exc:
            self.failed.append(name)
            print(f"  FAIL  {name}: {type(exc).__name__}: {exc}")
            return
        if note and note.startswith("skip:"):
            self.skipped.append(name)
            print(f"  SKIP  {name}: {note[5:].strip()}")
            return
        self.passed += 1
        print(f"  ok    {name} ({time.monotonic() - start:.1f}s){': ' + note if note else ''}")

    def get(self, path: str, expect: int = 200, **kw) -> Any:
        response = self.client.get(path, **kw)
        assert response.status_code == expect, f"GET {path} returned {response.status_code}: {response.text[:200]}"
        return response.json() if response.content else None

    def send(self, method: str, path: str, body: Any = None, expect: int = 200) -> Any:
        response = self.client.request(method, path, json=body)
        assert response.status_code == expect, f"{method} {path} returned {response.status_code}: {response.text[:200]}"
        return response.json() if response.content else None

    def wait_for_check(self, check_id: str, limit: float = 240) -> dict:
        deadline = time.monotonic() + limit
        while time.monotonic() < deadline:
            response = self.client.get(f"/api/checks/{check_id}")
            if response.status_code == 200:
                return response.json()
            assert response.status_code == 202, f"check failed: {response.text[:300]}"
            time.sleep(1)
        raise AssertionError("the check did not finish in time")


def claim_starting(result: dict, text: str) -> dict:
    return next(item for item in result["claims"] if item["claim"]["text"].startswith(text))


def of_kind(result: dict, kind: str) -> list[dict]:
    return [item for item in result["claims"] if item["claim"]["kind"] == kind]


def first_question() -> str:
    return json.loads(QUESTIONS.read_text(encoding="utf-8").splitlines()[0])["question"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--allow-spend", action="store_true", help="allow a run against real Bifrost and Tavily")
    args = parser.parse_args()

    try:
        health = httpx.get(f"{args.api.rstrip('/')}/api/health", timeout=20).json()
    except httpx.HTTPError as exc:
        print(f"Can't reach the API at {args.api} ({type(exc).__name__}). Start the backend first.")
        return 2
    demo = bool(health.get("demo_mode"))
    if not demo and not args.allow_spend:
        print("The backend is using real Bifrost and Tavily. This tour runs about 8 checks and spends credits.")
        print("Re-run with --allow-spend, or set DEMO_MODE=true in .env and restart the backend.")
        return 2

    tour = Tour(args.api, demo)
    print(f"ShelfLife feature tour against {args.api} ({'demo mode: invented data' if demo else 'real services'})\n")
    state: dict[str, Any] = {}

    if demo:
        scenarios = {item["id"]: item for item in tour.get("/api/demo")["scenarios"]}
        cloud, facts, vault = scenarios["cloud"], scenarios["facts"], scenarios["compare"]
    else:
        question = first_question()
        generated = tour.send("POST", "/api/generate-stale", {"question": question})
        cloud = {"question": question, "answer": generated["answer"], "context": None}
        facts = cloud
        second = tour.send("POST", "/api/generate-stale", {"question": question})
        vault = {"question": question, "answers": [
            {"app": "First answer", "answer": generated["answer"]},
            {"app": "Second answer", "answer": second["answer"]},
        ]}

    # --- core ----------------------------------------------------------------------
    def health_step():
        data = tour.get("/api/health")
        assert data["bifrost"]["ok"], f"Bifrost: {data['bifrost']['detail']}"
        assert data["tavily"]["ok"], f"Tavily: {data['tavily']['detail']}"
        assert not data["missing_settings"], f"missing {data['missing_settings']}"
        return f"Bifrost {data['bifrost']['detail']}, Tavily {data['tavily']['detail']}"

    tour.step("Health: Bifrost, virtual key and Tavily", health_step)

    def check_step():
        body = {"answer": cloud["answer"], "question": cloud["question"], "context": cloud.get("context")}
        created = tour.send("POST", "/api/checks", body, expect=202)
        events = tour.client.get(f"/api/checks/{created['check_id']}/events", timeout=240).text
        assert "event: done" in events or "done" in events, "no done event in the live stream"
        result = tour.wait_for_check(created["check_id"])
        state["cloud"] = result
        assert result["claims"], "no claims found"
        for item in result["claims"]:
            assert item["verdict"] in ("fresh", "uncertain", "stale", "unverified", "not_time_sensitive", "error")
        if tour.demo:
            assert result["guard"]["action"] == "withhold"
        return f"{len(result['claims'])} claims, score {result['answer_score']}, advice {result['guard']['action']}"

    tour.step("Check an answer with live progress (SSE)", check_step)

    def verify_step():
        result = tour.send("POST", "/api/verify", {"answer": facts["answer"], "question": facts["question"]})
        state["facts"] = result
        if tour.demo:
            assert {"stale", "uncertain", "fresh", "unverified", "not_time_sensitive", "error"} <= set(result["verdict_counts"])
        return f"verdicts {result['verdict_counts']}"

    tour.step("One-call API: POST /api/verify", verify_step)

    def zero_explained():
        if not tour.demo:
            return "skip: needs known data (demo mode)"
        price = claim_starting(state["cloud"], "Nimbus Cloud's Starter plan costs")
        assert price["verdict"] == "stale" and price["freshness_score"] <= 5
        assert price["confidence"] > 0.5, "a near-zero score should come with strong evidence"
        assert price["change"]["old_value"] and price["change"]["new_value"]
        return f"score {price['freshness_score']}, evidence strength {round(price['confidence'] * 100)}"

    tour.step("Low score means strong contradicting evidence", zero_explained)

    # --- reasoning features ----------------------------------------------------------
    def assumptions():
        if not tour.demo:
            kinds = {item["claim"]["kind"] for item in state["cloud"]["claims"]}
            return f"kinds found: {sorted(kinds)}"
        assumption = of_kind(state["cloud"], "assumption")
        assert assumption and assumption[0]["claim"]["span"] is None
        return assumption[0]["claim"]["text"]

    tour.step("#2 Hidden assumptions", assumptions)

    def numbers():
        if not tour.demo:
            return "skip: needs known data (demo mode)"
        total = claim_starting(state["cloud"], "For 10 seats")
        assert total["claim"]["kind"] == "calculation" and total["verdict"] == "stale"
        recalc = total["recalculation"]
        assert recalc["recomputed"] != recalc["stated"]
        return f"stated {recalc['stated']}, recomputed {recalc['recomputed']}"

    tour.step("#8 Numerical claim auditor", numbers)

    def dependencies():
        if not tour.demo:
            return "skip: needs known data (demo mode)"
        recommendation = of_kind(state["cloud"], "recommendation")[0]
        assert recommendation["affected_by"], "the recommendation should list what it relies on"
        return f"recommendation relies on {len(recommendation['affected_by'])} claims"

    tour.step("#11 Dependency freshness graph", dependencies)

    def decisions():
        if not tour.demo:
            return "skip: needs known data (demo mode)"
        recommendation = of_kind(state["cloud"], "recommendation")[0]
        assert recommendation["decision"]["holds"] == "no" and recommendation["decision"]["revised"]
        return recommendation["decision"]["revised"]

    tour.step("#1 Decision audit trail", decisions)

    def api_change():
        if not tour.demo:
            return "skip: needs known data (demo mode)"
        api = of_kind(state["cloud"], "api_usage")
        assert api and api[0]["verdict"] == "stale"
        return f"{api[0]['change']['change_type']}: {api[0]['change']['new_value']}"

    tour.step("#6 API breaking-change detection", api_change)

    def availability():
        if not tour.demo:
            return "skip: needs known data (demo mode)"
        item = of_kind(state["cloud"], "availability")
        assert item, "no availability claim"
        assert state["cloud"]["context"]["country"] == "india"
        return f"{item[0]['claim']['text']} -> {item[0]['verdict']}"

    tour.step("#14 Live availability for the reader's country", availability)

    def context_step():
        if not tour.demo:
            return "skip: needs known data (demo mode)"
        notes = [item["context_note"] for item in state["cloud"]["claims"] if item.get("context_note")]
        return f"{len(notes)} context notes" if notes else "context sent to search and judging"

    tour.step("#5 Real-time context verification", context_step)

    # --- after a check ---------------------------------------------------------------
    def export_step():
        response = tour.client.get(f"/api/checks/{state['cloud']['id']}/export", params={"format": "md"})
        assert response.status_code == 200 and response.text.startswith("#")
        return f"{len(response.text.splitlines())} lines of Markdown"

    tour.step("Export a report (Markdown)", export_step)

    def history_step():
        body = {"answer": cloud["answer"], "question": cloud["question"], "context": cloud.get("context")}
        second = tour.send("POST", "/api/verify", body)
        timeline = tour.get(f"/api/checks/{second['id']}/history")
        assert len(timeline["checks"]) >= 2, "re-checking the same answer should build a history"
        return f"{len(timeline['checks'])} checks of this answer"

    tour.step("Check history across re-checks", history_step)

    tour.step("Affected earlier answers", lambda: f"{len(tour.get(f'/api/checks/' + state['cloud']['id'] + '/affected')['claims'])} stale claims with earlier answers")
    tour.step("Re-check watchlist", lambda: f"{len(tour.get('/api/watchlist', params={'days': 30})['items'])} claims due within 30 days")

    def compare_step():
        result = tour.send("POST", "/api/compare", {"question": vault["question"], "answers": vault["answers"]})
        assert result["clusters"] and len(result["apps"]) == len(vault["answers"])
        if tour.demo:
            assert result["conflicts"] >= 2
            best = max(result["apps"], key=lambda app: app["fresh"])
            assert best["app"] == "Docs assistant"
        return f"{len(result['clusters'])} facts, {result['conflicts']} conflicts"

    tour.step("#3 Contradictions across AI apps", compare_step)

    def passport_step():
        claims = tour.get("/api/claims")["claims"]
        assert claims, "the registry is empty"
        passport = tour.get(f"/api/claims/{claims[0]['id']}")
        assert passport["history"], "a passport needs a history"
        stale = tour.get("/api/claims", params={"status": "stale"})["claims"]
        assert all(item["status"] == "stale" for item in stale)
        return f"{len(claims)} claims in the registry; {passport['id']} checked {passport['checks']}x"

    tour.step("#7 Provenance passport", passport_step)

    def links_step():
        result = tour.send("POST", "/api/links/check", {"check_id": state["cloud"]["id"]})
        assert result["results"], "no links to check"
        if tour.demo:
            assert {"ok", "gone", "moved"} <= set(result["counts"])
        return ", ".join(f"{count} {status}" for status, count in result["counts"].items())

    tour.step("#9 Link rot monitor", links_step)

    def regression_step():
        must = "Acme" if tour.demo else ""
        test = tour.send("POST", "/api/tests", {
            "name": "Feature tour test", "question": facts["question"],
            "must_include": [must] if must else [],
        }, expect=201)
        tour.cleanup.append(lambda: tour.client.delete(f"/api/tests/{test['id']}"))
        run = tour.send("POST", f"/api/tests/{test['id']}/run", {})
        runs = tour.get(f"/api/tests/{test['id']}/runs")["runs"]
        assert runs and runs[0]["id"] == run["id"]
        if tour.demo:
            assert run["passed"] is False and any(problem.startswith("Stale") for problem in run["problems"])
        return f"{'passed' if run['passed'] else 'failed'}: {'; '.join(run['problems'][:2]) or 'no problems'}"

    tour.step("#13 Regression testing", regression_step)

    def profile_step():
        profile = tour.send("POST", "/api/profiles", {"name": "Feature tour profile", "context": {"country": "india"}}, expect=201)
        tour.cleanup.append(lambda: tour.client.delete(f"/api/profiles/{profile['id']}"))
        result = tour.send("POST", "/api/verify", {"answer": facts["answer"], "question": facts["question"], "profile_id": profile["id"]})
        assert result["profile_id"] == profile["id"] and result["profile_version"] == 1
        updated = tour.send("PUT", f"/api/profiles/{profile['id']}", {"name": profile["name"], "context": {"country": "singapore"}})
        assert updated["version"] == 2
        listed = next(item for item in tour.get("/api/profiles")["profiles"] if item["id"] == profile["id"])
        assert any(check["id"] == result["id"] for check in listed["drifted_checks"])
        return "profile changed, older check flagged"

    tour.step("#4 Personalization drift (context profiles)", profile_step)

    def batch_step():
        items = [{"question": cloud["question"], "answer": cloud["answer"]},
                 {"question": facts["question"], "answer": facts["answer"]}]
        batch_id = tour.send("POST", "/api/batch", {"items": items}, expect=202)["batch_id"]
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            batch = tour.get(f"/api/batch/{batch_id}")
            if batch["finished"]:
                break
            time.sleep(1)
        assert batch["finished"], "the batch did not finish"
        assert all(item["status"] == "done" for item in batch["items"]), batch["items"]
        return f"{len(batch['items'])} answers checked"

    tour.step("Batch checks", batch_step)

    def dashboard_step():
        data = tour.get("/api/dashboard")
        assert data["totals"]["checks"] >= 1 and len(data["daily"]) == 14
        return f"{data['totals']['checks']} checks, {data['totals']['claims_checked']} claims, {len(data['drift'])} drift alerts"

    tour.step("Dashboard", dashboard_step)

    def system_step():
        data = tour.get("/api/system")
        assert data["settings"]["model_fast"] and data["settings"]["model_strong"]
        state["webhook"] = data["settings"]["alert_webhook"]
        return f"providers {data['settings']['providers']}, cache: {data['cache_plugin']['detail']}"

    tour.step("System status", system_step)
    tour.step("Stale-answer webhook", lambda: "configured" if state.get("webhook") else "skip: set ALERT_WEBHOOK_URL in .env to test")
    tour.step("Evaluation results endpoint", lambda: "results found" if tour.get("/api/evaluation")["available"] else "no results yet (run the evaluation)")

    for undo in tour.cleanup:
        try:
            undo()
        except httpx.HTTPError:
            pass

    print(f"\n{tour.passed} passed, {len(tour.failed)} failed, {len(tour.skipped)} skipped")
    if tour.failed:
        print("Failed: " + "; ".join(tour.failed))
    return 1 if tour.failed else 0


if __name__ == "__main__":
    sys.exit(main())
