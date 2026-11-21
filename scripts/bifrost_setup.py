"""Check ShelfLife's Bifrost setup, and optionally turn on Bifrost's response cache.

    cd backend
    uv run python ../scripts/bifrost_setup.py
    uv run python ../scripts/bifrost_setup.py --enable-cache

Admin calls (reading or changing plugins) use BIFROST_ADMIN_USER and
BIFROST_ADMIN_PASSWORD if the dashboard is password-protected, and otherwise the
BIFROST_SETUP_TOKEN from .env.
"""

from __future__ import annotations

import argparse
import base64
import os
import sys
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import config  # noqa: E402

# Exact-match caching needs no embedding model. Entries expire within a day so the
# cache can't make our answers stale.
CACHE_PLUGIN_CONFIG = {"dimension": 1, "ttl": "24h", "cache_by_model": True, "cache_by_provider": True}

VECTOR_STORE_HELP = """
Bifrost's cache needs a vector store, set in config.json in Bifrost's app folder.
Add this block, then restart Bifrost:

    "vector_store": {"enabled": true, "type": "redis", "config": {"addr": "localhost:6379"}}

With Docker Compose, use "redis:6379" instead: inside the Bifrost container,
localhost is the container itself.

Redis must support search commands: Redis 8, or Redis Stack. Without Docker you can use:
  - WSL: install Redis 8 from Redis's own apt repository (see redis.io's Linux
    install guide). Ubuntu's default redis-server package is too old.
  - Redis Cloud's free plan (put its host:port in addr, and its password in password)
Bifrost also supports Qdrant, Weaviate and Pinecone. See
https://docs.getbifrost.ai/features/semantic-caching
"""

problems: list[str] = []


def report(ok: bool, label: str, detail: str) -> None:
    print(f"[{'ok' if ok else '!!'}] {label}: {detail}")
    if not ok:
        problems.append(label)


def admin_headers(env: dict[str, str]) -> dict[str, str]:
    user = env.get("BIFROST_ADMIN_USER")
    password = env.get("BIFROST_ADMIN_PASSWORD")
    if user and password:
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        return {"Authorization": f"Basic {token}"}
    if env.get("BIFROST_SETUP_TOKEN"):
        return {"X-Bifrost-Setup-Token": env["BIFROST_SETUP_TOKEN"]}
    return {}


def providers_of(model: str, fallbacks: list[str]) -> list[str]:
    return sorted({name.split("/", 1)[0] for name in [model, *fallbacks] if "/" in name})


def check_models(settings: config.Settings) -> None:
    for stage, model, fallbacks in (
        ("MODEL_FAST", settings.model_fast, settings.fallbacks_fast_list),
        ("MODEL_STRONG", settings.model_strong, settings.fallbacks_strong_list),
    ):
        if not model:
            report(False, stage, "not set in .env")
            continue
        providers = providers_of(model, fallbacks)
        if len(providers) < 2:
            report(
                False,
                stage,
                f"{model} has no fallback on another provider. Add one to "
                f"FALLBACKS_{stage.removeprefix('MODEL_')} to demo failover.",
            )
        else:
            report(True, stage, f"{model}, fallbacks {', '.join(fallbacks)}")


def find_plugin(payload: object, name: str) -> dict | None:
    plugins = payload.get("plugins") if isinstance(payload, dict) else payload
    for plugin in plugins or []:
        if isinstance(plugin, dict) and plugin.get("name") == name:
            return plugin
    return None


def check_cache(client: httpx.Client, base: str, admin: dict[str, str], enable: bool) -> None:
    response = client.get(f"{base}/api/plugins", headers=admin)
    if response.status_code in (401, 403):
        report(
            False,
            "Cache plugin",
            "Bifrost refused the admin call. Set BIFROST_SETUP_TOKEN, or "
            "BIFROST_ADMIN_USER and BIFROST_ADMIN_PASSWORD, in .env.",
        )
        return
    plugin = find_plugin(response.json(), "semantic_cache") if response.status_code == 200 else None
    if plugin and plugin.get("enabled"):
        report(True, "Cache plugin", "semantic_cache is enabled")
        return
    if not enable:
        report(False, "Cache plugin", "not enabled. Run again with --enable-cache.")
        return

    body = {"enabled": True, "path": "", "config": CACHE_PLUGIN_CONFIG}
    try:
        # Loading a plugin can take a while, so allow longer than other calls.
        if plugin:
            result = client.put(
                f"{base}/api/plugins/semantic_cache", headers=admin, json=body, timeout=90
            )
        else:
            result = client.post(
                f"{base}/api/plugins",
                headers=admin,
                json={"name": "semantic_cache", **body},
                timeout=90,
            )
    except httpx.HTTPError as exc:
        report(False, "Cache plugin", f"no answer from Bifrost ({type(exc).__name__})")
        return
    if result.status_code < 300:
        report(True, "Cache plugin", "enabled in exact-match mode with a 24 hour TTL")
        return
    message = result.text[:300]
    report(False, "Cache plugin", f"Bifrost refused to enable it: {message}")
    if "store is required" in message:
        print(VECTOR_STORE_HELP)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--enable-cache", action="store_true", help="turn on the cache plugin")
    args = parser.parse_args()

    env = {**dotenv_values(config.ROOT_DIR / ".env"), **os.environ}
    env = {key: value for key, value in env.items() if value}
    settings = config.get_settings()
    base = settings.bifrost_url.rstrip("/")

    with httpx.Client(timeout=10) as client:
        try:
            client.get(f"{base}/health").raise_for_status()
        except httpx.HTTPError as exc:
            report(False, "Bifrost", f"not reachable at {base} ({type(exc).__name__})")
            return 1
        report(True, "Bifrost", f"reachable at {base}")

        status = client.get(f"{base}/api/session/is-auth-enabled").json()
        enforced = bool(status.get("inference_auth_enforced"))

        if settings.bifrost_vk:
            quota = client.get(
                f"{base}/api/governance/virtual-keys/quota",
                headers={"x-bf-vk": settings.bifrost_vk},
            )
            if quota.status_code == 200:
                data = quota.json()
                budgets = data.get("budgets") or []
                spend = ", ".join(
                    f"${b.get('current_usage', 0):.4f} of ${b.get('max_limit', 0):.2f} "
                    f"per {b.get('reset_duration')}"
                    for b in budgets
                )
                report(
                    bool(data.get("is_active", True)),
                    "Virtual key",
                    f"'{data.get('virtual_key_name')}'"
                    + (f", budget {spend}" if spend else ", no budget set"),
                )
                if not budgets:
                    print("     Add a budget to the key in the dashboard for the governance demo.")
            else:
                report(False, "Virtual key", f"Bifrost rejected BIFROST_VK (HTTP {quota.status_code})")
        elif enforced:
            report(
                False,
                "Virtual key",
                "Bifrost requires one. Create it under Virtual Keys in the dashboard, "
                "allow your providers and models, then set BIFROST_VK in .env.",
            )
        else:
            report(True, "Virtual key", "not used, and Bifrost doesn't require one")

        check_models(settings)
        check_cache(client, base, admin_headers(env), args.enable_cache)

    print("\nAll set." if not problems else f"\n{len(problems)} thing(s) to fix: {', '.join(problems)}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
