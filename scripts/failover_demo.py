"""Walk through the Bifrost part of the demo from the terminal.

    cd backend
    uv run python ../scripts/failover_demo.py
    uv run python ../scripts/failover_demo.py --answer-file answer.txt

1. Check an answer and show which model served each call.
2. Check it again: Bifrost's cache answers repeat calls, so cost and time drop.
3. Pause while you break the primary provider in the Bifrost dashboard, then check
   again with the cache skipped, so the fallback has to answer.

The backend must be running. With no answer file, the script asks MODEL_STALE to
answer a question first.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import httpx

DEFAULT_QUESTION = (
    "How much does ChatGPT Plus cost per month, who is the CEO of OpenAI, "
    "and what is its newest model?"
)


def run_check(client: httpx.Client, answer: str, use_cache: bool) -> dict:
    created = client.post("/api/checks", json={"answer": answer, "use_cache": use_cache})
    if created.status_code != 202:
        raise SystemExit(f"Could not start a check: {created.text[:300]}")
    check_id = created.json()["check_id"]

    event = None
    with client.stream("GET", f"/api/checks/{check_id}/events", timeout=None) as response:
        for line in response.iter_lines():
            if line.startswith("event: "):
                event = line.removeprefix("event: ")
                if event == "claim_scored":
                    print(".", end="", flush=True)
            elif line.startswith("data: ") and event in ("done", "error"):
                print()
                data = json.loads(line.removeprefix("data: "))
                if event == "error":
                    raise SystemExit(f"The check failed: {data['message']}")
                return data
    raise SystemExit("The event stream ended before the check finished.")


def summarise(label: str, result: dict) -> dict:
    metrics = result["metrics"]
    cost = f"${metrics['cost_usd']:.4f}"
    if metrics["unpriced_calls"]:
        cost += f" (+{metrics['unpriced_calls']} unpriced calls)"
    score = result["answer_score"]
    print(
        f"{label}: freshness {score if score is not None else 'n/a'}/100, "
        f"{len(result['claims'])} claims, {metrics['llm_calls']} LLM calls, "
        f"{metrics['cache_hits']} cache hits, {cost}, "
        f"{metrics['latency_ms'] / 1000:.1f}s, {metrics['tavily_credits']} Tavily credits"
    )
    served = Counter(
        claim["llm"]["served_by"] or "unknown" for claim in result["claims"] if claim.get("llm")
    )
    if served:
        print("  Claims judged by: " + ", ".join(f"{m} x{n}" for m, n in served.items()))
    fallbacks = Counter(
        (e["stage"], f"{e['provider']}/{e['model']}", f"{e['primary_provider']}/{e['primary_model']}")
        for e in metrics["fallback_events"]
    )
    for (stage, served, primary), count in fallbacks.items():
        print(f"  Fallback x{count}: {stage} served by {served} instead of {primary}")
    return metrics


def pause(message: str) -> None:
    print(f"\n{message}")
    if sys.stdin.isatty():
        input("Press Enter to continue... ")


def main() -> int:
    parser = argparse.ArgumentParser(description="Bifrost cache and failover demo.")
    parser.add_argument("--api", default="http://localhost:8000", help="ShelfLife API address")
    parser.add_argument("--answer-file", type=Path, help="check this answer instead")
    parser.add_argument("--question", default=DEFAULT_QUESTION, help="question for MODEL_STALE")
    args = parser.parse_args()

    with httpx.Client(base_url=args.api, timeout=120) as client:
        if args.answer_file:
            answer = args.answer_file.read_text(encoding="utf-8")
        else:
            generated = client.post("/api/generate-stale", json={"question": args.question})
            if generated.status_code != 200:
                raise SystemExit(f"Could not generate an answer: {generated.text[:300]}")
            answer = generated.json()["answer"]
            print(f"Answer from {generated.json()['model']}:\n{answer}\n")

        print("Run 1: first check")
        first = summarise("Run 1", run_check(client, answer, use_cache=True))

        print("\nRun 2: the same answer again, so Bifrost can answer from its cache")
        second = summarise("Run 2", run_check(client, answer, use_cache=True))
        print(
            f"  Cache hits {first['cache_hits']} -> {second['cache_hits']}, "
            f"cost ${first['cost_usd']:.4f} -> ${second['cost_usd']:.4f}, "
            f"time {first['latency_ms'] / 1000:.1f}s -> {second['latency_ms'] / 1000:.1f}s"
        )
        if second["cache_hits"] == 0:
            print("  No cache hits: is the cache plugin on? Run scripts/bifrost_setup.py.")

        pause(
            "Now break the primary provider for MODEL_STRONG: disable it in the Bifrost "
            "dashboard, or give it a wrong API key."
        )
        print("Run 3: the cache is skipped, so every call has to reach a provider")
        third = summarise("Run 3", run_check(client, answer, use_cache=False))
        if not third["fallback_events"]:
            print("  No fallbacks were used. Check that the primary provider is really broken.")
        pause("Remember to restore the primary provider in the Bifrost dashboard.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
