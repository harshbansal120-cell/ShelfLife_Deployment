"""Demo mode: the real pipeline against simulated Bifrost, Tavily and web pages.

Turn it on with DEMO_MODE=true in .env. Nothing here needs keys or spends credits,
and demo checks are stored apart from real ones.
"""

from __future__ import annotations

import httpx

from app import config
from app.demo.simulator import FACTS_QUESTION, SCENARIOS, SEED_DOCUMENTS, SEED_EDGES, Simulator

_simulator: Simulator | None = None


def active() -> bool:
    return config.get_settings().demo_mode


def activate() -> None:
    """Point every outgoing client at the simulator and fill in demo settings."""
    global _simulator
    from app import links, llm, search

    settings = config.get_settings()
    settings.bifrost_url = "http://bifrost.internal"
    settings.bifrost_vk = settings.bifrost_vk or "sk-bf-workspace"
    settings.tavily_api_key = settings.tavily_api_key or "tvly-workspace"
    settings.bifrost_setup_token = settings.bifrost_setup_token or "workspace"
    settings.model_fast = settings.model_fast or "primary/fast-model"
    settings.model_strong = settings.model_strong or "primary/strong-model"
    settings.model_stale = settings.model_stale or "primary/legacy-model"
    settings.fallbacks_fast = settings.fallbacks_fast or "secondary/fast-model"
    settings.fallbacks_strong = settings.fallbacks_strong or "secondary/strong-model"
    settings.history_path = settings.history_path.with_name("history-demo.sqlite3")
    settings.search_cache_path = settings.search_cache_path.with_name("search-demo.sqlite3")
    _simulator = Simulator()
    transport = httpx.MockTransport(_simulator)
    llm._transport = transport
    search._transport = transport
    links._transport = transport
    # The simulator answers every request, so the public-address check would only
    # reject its invented hosts; real addresses are refused instead.
    links._public_only = False
    links._demo_suffix = ".example"


def scenarios() -> list[dict]:
    return SCENARIOS


async def seed() -> None:
    """Fill an empty workspace with documents built on the scenarios' facts, a declared
    dependency between claims, and a regression test, so impact tracing and the
    autopilot have something to work on from the start."""
    from app import impact, workspace
    from app.passport import passport_id

    if impact.list_documents():
        return
    for document in SEED_DOCUMENTS:
        await impact.register_document(impact.DocumentRequest(**document))
    for upstream, downstream, note in SEED_EDGES:
        try:
            impact.add_edge(impact.EdgeRequest(
                upstream=passport_id(upstream), downstream=passport_id(downstream), note=note,
            ))
        except ValueError:
            pass
    if not workspace.list_tests():
        workspace.save_test("Acme pricing answer", FACTS_QUESTION, None, ["$25"])
