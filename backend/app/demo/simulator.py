"""Simulated Bifrost, Tavily and web pages for demo mode and tests.

Every company, product and figure here is invented, so no real-world fact is
stored in the code. The simulator answers the real pipeline's requests, so demo
mode exercises the same code paths as a live run without keys or credits.
"""

from __future__ import annotations

import asyncio
import json
import random
import re
from datetime import date, timedelta
from typing import Any

import httpx


def ago(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


# --- scenarios ------------------------------------------------------------------

CLOUD_QUESTION = "Which cloud host is cheapest for a 10-person startup in India, and how do I deploy to it?"
CLOUD_ANSWER = (
    "For a 10-person startup, Nimbus Cloud is the cheapest option. Nimbus Cloud's Starter plan "
    "costs $20 per seat per month, while Stratus Cloud charges $25 per seat per month. For 10 "
    "seats, Nimbus Cloud costs $200 a month, saving you $50 a month compared with Stratus Cloud. "
    "Nimbus Cloud is available in India. To deploy, call nimbus.deploy(app) from the Nimbus SDK."
)

FACTS_QUESTION = "How much does Acme Cloud cost, and who runs Acme?"
FACTS_ANSWER = (
    "Acme Cloud costs $10 per month on the Starter plan. The latest Acme SDK is version 3.2. "
    "Bo Lee is the CEO of Acme. Acme has 40 million users. Acme was founded in 1999 in Oslo. "
    "The Orbit feature is still in beta. The Data Act requires Acme to keep records for 5 years. "
    "Acme's spring sale is still running."
)

RELEASE_QUESTION = "What is the latest stable version of the Orion runtime, and which versions are no longer supported?"
RELEASE_ANSWER = (
    "The latest stable release of the Orion runtime is version 4.2, launched on March 4, 2025. "
    "Orion 1.x and 2.x are no longer supported."
)


def long_date(days: int) -> str:
    """A date written the way answers write it, such as "March 4, 2025"."""
    day = date.today() - timedelta(days=days)
    return f"{day:%B} {day.day}, {day.year}"


ORION_44_RELEASED = 41

HISTORY_QUESTION = "What was the latest Orion runtime release in June 2025, and what did Acme Cloud's Starter plan cost then?"
HISTORY_ANSWER = (
    "In June 2025, the latest stable release of the Orion runtime was version 4.2. At that time, "
    "Acme Cloud's Starter plan cost $10 per month. Today the latest Orion release is version 4.2."
)

VAULT_QUESTION = "How many users can an Acme Vault workspace have, and what does it cost?"
VAULT_ANSWERS = [
    {"app": "Sales assistant", "answer": "Acme Vault supports up to 10,000 users per workspace and costs $12 per user per month."},
    {"app": "Support assistant", "answer": "Acme Vault supports up to 5,000 users per workspace and costs $12 per user per month."},
    {"app": "Docs assistant", "answer": "Acme Vault supports up to 8,000 users per workspace and costs $15 per user per month."},
]

SCENARIOS = [
    {
        "id": "cloud",
        "label": "Cloud recommendation",
        "description": "A recommendation built on prices, a calculation, a hidden assumption, an API call and availability.",
        "question": CLOUD_QUESTION,
        "answer": CLOUD_ANSWER,
        "context": {"country": "india"},
    },
    {
        "id": "facts",
        "label": "Product facts",
        "description": "Every kind of verdict: stale, uncertain, fresh, unverified and couldn't check.",
        "question": FACTS_QUESTION,
        "answer": FACTS_ANSWER,
        "context": None,
    },
    {
        "id": "release",
        "label": "Release notes",
        "description": "A version that moved on, the release date written beside it, and a support list that grew.",
        "question": RELEASE_QUESTION,
        "answer": RELEASE_ANSWER,
        "context": None,
    },
    {
        "id": "history",
        "label": "Timeline question",
        "description": "Claims about June 2025 judged as of June 2025, beside the same fact claimed for today.",
        "question": HISTORY_QUESTION,
        "answer": HISTORY_ANSWER,
        "context": None,
    },
    {
        "id": "compare",
        "label": "Three assistants disagree",
        "description": "The same question answered differently by a sales, support and docs assistant.",
        "question": VAULT_QUESTION,
        "answers": VAULT_ANSWERS,
    },
]


def claim(ref, kind, text, source, category, queries=(), entities=("Acme",), **extra):
    return {
        "ref": ref, "kind": kind, "text": text, "source_text": source, "span": None,
        "category": category, "entities": list(entities), "time_sensitive": category != "static",
        "search_queries": list(queries), "official_domains": extra.pop("official", []), **extra,
    }


CLOUD_EXTRACTION = [
    claim("r1", "recommendation", "Nimbus Cloud is the cheapest option for a 10-person startup.",
          "Nimbus Cloud is the cheapest option", "pricing", entities=("Nimbus Cloud",),
          depends_on=["r2", "r3", "r4", "r5", "r8"]),
    claim("r2", "fact", "Nimbus Cloud's Starter plan costs $20 per seat per month.",
          "Nimbus Cloud's Starter plan costs $20 per seat per month", "pricing",
          ["Nimbus Cloud Starter plan price"], ("Nimbus Cloud", "Nimbus"), number=20, official=["nimbus.example"]),
    claim("r3", "fact", "Stratus Cloud charges $25 per seat per month.",
          "Stratus Cloud charges $25 per seat per month", "pricing",
          ["Stratus Cloud price per seat"], ("Stratus Cloud", "Stratus"), number=25),
    claim("r4", "calculation", "For 10 seats, Nimbus Cloud costs $200 a month.",
          "Nimbus Cloud costs $200 a month", "pricing", entities=("Nimbus Cloud",),
          depends_on=["r2"], formula="{r2} * 10", number=200),
    claim("r5", "calculation", "Choosing Nimbus Cloud saves $50 a month compared with Stratus Cloud.",
          "saving you $50 a month", "pricing", entities=("Nimbus Cloud",),
          depends_on=["r2", "r3"], formula="({r3} - {r2}) * 10", number=50),
    claim("r6", "availability", "Nimbus Cloud is available in India.",
          "Nimbus Cloud is available in India", "product_status",
          ["Nimbus Cloud regions"], ("Nimbus Cloud", "Nimbus")),
    claim("r7", "api_usage", "nimbus.deploy(app) is the current way to deploy with the Nimbus SDK.",
          "call nimbus.deploy(app)", "version_api", ["Nimbus SDK deploy method"], ("Nimbus SDK", "Nimbus")),
    claim("r8", "assumption", "Nimbus Cloud's Starter plan allows at least 10 seats.", "",
          "product_status", ["Nimbus Cloud Starter plan seat limit"], ("Nimbus Cloud", "Nimbus"), number=10),
]

FACTS_EXTRACTION = [
    claim("f1", "fact", "Acme Cloud costs $10 per month on the Starter plan.",
          "Acme Cloud costs $10 per month on the Starter plan", "pricing", ["Acme Cloud price"],
          ("Acme Cloud", "Acme"), number=10),
    claim("f2", "fact", "The latest Acme SDK is version 3.2.", "The latest Acme SDK is version 3.2",
          "version_api", ["Acme SDK latest version"], number=3.2),
    claim("f3", "fact", "Bo Lee is the CEO of Acme.", "Bo Lee is the CEO of Acme", "leadership_role", ["Acme CEO"]),
    claim("f4", "fact", "Acme has 40 million users.", "Acme has 40 million users", "statistic",
          ["Acme number of users"], number=40),
    claim("f5", "fact", "Acme was founded in 1999 in Oslo.", "Acme was founded in 1999 in Oslo", "static"),
    claim("f6", "fact", "Acme's Orbit feature is still in beta.", "The Orbit feature is still in beta",
          "product_status", ["Acme Orbit beta"]),
    claim("f7", "fact", "The Data Act requires Acme to keep records for 5 years.",
          "The Data Act requires Acme to keep records for 5 years", "law_regulation",
          ["Data Act record keeping period"], number=5),
    claim("f8", "fact", "Acme's spring sale is still running.", "Acme's spring sale is still running",
          "event_status", ["Acme spring sale"]),
]


RELEASE_EXTRACTION = [
    claim("o1", "fact", "The latest stable release of the Orion runtime is version 4.2.",
          "The latest stable release of the Orion runtime is version 4.2", "version_api",
          ["Orion runtime latest stable release"], ("Orion runtime", "Orion"), number=4.2, official=["orion.example"]),
    # A detail of o1's value: true forever on its own, wrong once "4.2" becomes "4.4".
    claim("o2", "fact", "Orion 4.2 was launched on March 4, 2025.",
          "version 4.2, launched on March 4, 2025", "static", ["Orion 4.2 release date"],
          ("Orion runtime", "Orion"), depends_on=["o1"]),
    claim("o3", "fact", "As of today, Orion 1.x and 2.x are the versions that no longer receive support.",
          "Orion 1.x and 2.x are no longer supported", "product_status",
          ["Orion runtime end of life versions"], ("Orion runtime", "Orion"), official=["orion.example"]),
]


HISTORY_EXTRACTION = [
    # True for its time: 4.3 only came out in September 2025.
    claim("h1", "fact", "In June 2025, the latest stable release of the Orion runtime was version 4.2.",
          "In June 2025, the latest stable release of the Orion runtime was version 4.2", "version_api",
          ["Orion runtime release history"], ("Orion runtime", "Orion"), number=4.2, official=["orion.example"],
          time_frame="past", as_of="June 2025", as_of_date="2025-06"),
    # Wrong even then: the price history says $8 until August 2025.
    claim("h2", "fact", "In June 2025, Acme Cloud's Starter plan cost $10 per month.",
          "At that time, Acme Cloud's Starter plan cost $10 per month", "pricing",
          ["Acme Cloud Starter plan price history"], ("Acme Cloud", "Acme"), number=10,
          time_frame="past", as_of="June 2025", as_of_date="2025-06"),
    # The same fact as h1, but claimed for today: stale.
    claim("h3", "fact", "The latest stable release of the Orion runtime is version 4.2.",
          "Today the latest Orion release is version 4.2", "version_api",
          ["Orion runtime latest stable release"], ("Orion runtime", "Orion"), number=4.2, official=["orion.example"]),
]


def document_extraction(text: str) -> list[dict]:
    """Claims in the seeded documents, found by pattern so corrected versions work too."""
    found: list[dict] = []

    def add(pattern: str, build) -> re.Match | None:
        match = re.search(pattern, text)
        if match:
            found.append(build(match))
        return match

    price = add(r"Nimbus Cloud's Starter plan costs \$(\d+) per seat per month", lambda m: claim(
        "d-price", "fact", f"Nimbus Cloud's Starter plan costs ${m.group(1)} per seat per month.", m.group(0),
        "pricing", ["Nimbus Cloud Starter plan price"], ("Nimbus Cloud", "Nimbus"), number=float(m.group(1)),
        official=["nimbus.example"]))
    add(r"Nimbus Cloud is available in India", lambda m: claim(
        "d-region", "availability", "Nimbus Cloud is available in India.", m.group(0), "product_status",
        ["Nimbus Cloud regions"], ("Nimbus Cloud", "Nimbus")))
    add(r"your team of 10 fits the Starter plan", lambda m: claim(
        "d-seats", "fact", "Nimbus Cloud's Starter plan allows at least 10 seats.", m.group(0), "product_status",
        ["Nimbus Cloud Starter plan seat limit"], ("Nimbus Cloud", "Nimbus"), number=10))
    add(r"Starter plan now allows up to (\d+) seats", lambda m: claim(
        "d-seats", "fact", f"Nimbus Cloud's Starter plan allows up to {m.group(1)} seats.", m.group(0),
        "product_status", ["Nimbus Cloud Starter plan seat limit"], ("Nimbus Cloud", "Nimbus"),
        number=float(m.group(1))))
    add(r"call (nimbus\.[\w.]+\(app\))", lambda m: claim(
        "d-api", "api_usage", f"{m.group(1)} is the current way to deploy with the Nimbus SDK.", m.group(0),
        "version_api", ["Nimbus SDK deploy method"], ("Nimbus SDK", "Nimbus")))
    if price:
        add(r"Nimbus Cloud is the cheapest option for your 10-person team", lambda m: claim(
            "d-pick", "recommendation", "Nimbus Cloud is the cheapest option for a 10-person startup.",
            m.group(0), "pricing", entities=("Nimbus Cloud",),
            depends_on=["d-price"] + (["d-region"] if "available in India" in text else [])))
        add(r"\$([\d,]+) a year", lambda m: claim(
            "d-year", "calculation", f"For 10 seats over 12 months, Nimbus Cloud costs ${m.group(1)} a year.",
            m.group(0), "pricing", entities=("Nimbus Cloud",), depends_on=["d-price"],
            formula="{d-price} * 10 * 12", number=float(m.group(1).replace(",", ""))))
    add(r"Orion runtime (\d+\.\d+), the latest stable release", lambda m: claim(
        "d-orion", "fact", f"The latest stable release of the Orion runtime is version {m.group(1)}.", m.group(0),
        "version_api", ["Orion runtime latest stable release"], ("Orion runtime", "Orion"),
        number=float(m.group(1)), official=["orion.example"]))
    add(r"Acme SDK (\d+\.\d+)", lambda m: claim(
        "d-sdk", "fact", f"The latest Acme SDK is version {m.group(1)}.", m.group(0), "version_api",
        ["Acme SDK latest version"], number=float(m.group(1))))
    return found


SEED_DOCUMENTS = [
    {
        "title": "Kestrel Labs hosting proposal",
        "kind": "proposal",
        "text": (
            "Proposal for Kestrel Labs. We recommend Nimbus Cloud. Nimbus Cloud is the cheapest option for "
            "your 10-person team. Nimbus Cloud's Starter plan costs $20 per seat per month, and Nimbus Cloud "
            "is available in India, close to your users."
        ),
    },
    {
        "title": "FY hosting budget projection",
        "kind": "projection",
        "text": (
            "Hosting budget. Nimbus Cloud's Starter plan costs $20 per seat per month. With 10 seats for 12 "
            "months, hosting comes to $2,400 a year, which fits the approved budget."
        ),
    },
    {
        "title": "Welcome email to Priya at Kestrel Labs",
        "kind": "email",
        "text": (
            "Hi Priya, as discussed, Nimbus Cloud's Starter plan costs $20 per seat per month, and your team "
            "of 10 fits the Starter plan. To deploy, call nimbus.deploy(app) from the Nimbus SDK. Best, Sam"
        ),
    },
    {
        "title": "Platform upgrade plan",
        "kind": "report",
        "text": (
            "Our services run on the Orion runtime 4.2, the latest stable release, and integrate through the "
            "Acme SDK 3.2. No upgrade work is planned this quarter."
        ),
    },
]

# Declared links between claims from different answers: the SDK targets the runtime.
SEED_EDGES = [
    ("The latest stable release of the Orion runtime is version 4.2.", "The latest Acme SDK is version 3.2.",
     "Acme SDK releases target the latest Orion runtime."),
]


def vault_extraction(answer: str) -> list[dict]:
    users = re.search(r"up to ([\d,]+) users", answer)
    price = re.search(r"\$(\d+) per user", answer)
    claims = []
    if users:
        claims.append(claim("v1", "fact", f"Acme Vault supports up to {users.group(1)} users per workspace.",
                            f"Acme Vault supports up to {users.group(1)} users per workspace", "version_api",
                            ["Acme Vault users per workspace limit"], ("Acme Vault", "Acme"),
                            number=float(users.group(1).replace(",", ""))))
    if price:
        claims.append(claim("v2", "fact", f"Acme Vault costs ${price.group(1)} per user per month.",
                            f"costs ${price.group(1)} per user per month", "pricing",
                            ["Acme Vault price per user"], ("Acme Vault", "Acme"), number=float(price.group(1))))
    return claims


def result(url, content, days, title="Page", score=0.9):
    return {"title": title, "url": url, "content": content, "score": score,
            "published_date": ago(days) if days is not None else None,
            "favicon": None}


def search_results() -> dict[str, list[dict]]:
    return {
        "Nimbus Cloud Starter plan price": [
            result("https://nimbus.example/pricing", "Pricing", 3, "Nimbus Cloud pricing", 0.95),
            result("https://technews.example/nimbus-price", "Nimbus Cloud raises its Starter plan to $28 per seat per month, effective this quarter.", 10, "Nimbus raises prices", 0.9),
            result("https://dailycloud.example/nimbus", "Nimbus Cloud raises its Starter plan to $28 per seat per month, effective this quarter!", 9, "Nimbus price rise", 0.85),
            result("https://oldblog.example/cheap-clouds", "Nimbus Cloud's Starter plan costs $20 per seat per month.", 400, "Cheapest clouds", 0.5),
        ],
        "Stratus Cloud price per seat": [
            result("https://stratus.example/pricing", "Stratus Cloud costs $25 per seat per month on every plan.", 6, "Stratus pricing"),
        ],
        "Nimbus Cloud regions": [
            result("https://nimbus.example/regions", "Nimbus Cloud regions: Mumbai (India), Singapore and Frankfurt.", 25, "Regions"),
        ],
        "Nimbus SDK deploy method": [
            result("https://nimbus.example/docs/changelog", "SDK 4.0: nimbus.deploy() is deprecated. Use nimbus.deployments.create(app) instead.", 15, "SDK changelog"),
        ],
        "Nimbus Cloud Starter plan seat limit": [
            result("https://nimbus.example/plans", "The Starter plan supports up to 5 seats. Teams of 6 or more need the Team plan.", 30, "Plans"),
        ],
        "Acme Cloud price": [
            result("https://acme.example/pricing", "The Acme Cloud Starter plan now costs $25 per month.", 4, "Acme pricing", 0.95),
            result("https://www.reuters.com/acme-price", "Acme raised its Starter plan to $25 per month this year.", 30, "Acme raises price", 0.9),
            result("https://oldblog.example/acme", "Acme Cloud costs $10 per month on the Starter plan.", 700, "Old post", 0.5),
        ],
        "Acme SDK latest version": [result("https://acme.example/sdk", "The latest Acme SDK is version 3.2.", 210, "SDK releases")],
        "Acme CEO": [
            result("https://acme.example/about", "Bo Lee is the chief executive of Acme.", 12, "About Acme", 0.95),
            result("https://techcrunch.com/acme", "Acme CEO Bo Lee spoke at the conference.", 40, "Acme at the conference", 0.9),
        ],
        "Acme number of users": [result("https://reddit.com/r/acme/1", "I heard Acme has 40 million users.", None, "Forum thread")],
        "Acme Orbit beta": [result("https://acme.example/orbit", "Orbit overview.", 5, "Orbit")],
        "Data Act record keeping period": [result("https://justice.gov/data-act", "The Data Act requires companies to keep records for 5 years.", 90, "Data Act")],
        "Acme spring sale": [result("https://acme.example/sale", "The Acme spring sale is running now.", 39, "Spring sale")],
        "Acme Vault users per workspace limit": [result("https://acme.example/vault/limits", "Each Acme Vault workspace supports up to 8,000 users.", 12, "Vault limits")],
        "Acme Vault price per user": [result("https://acme.example/vault/pricing", "Acme Vault costs $15 per user per month.", 8, "Vault pricing")],
        "Orion runtime latest stable release": [
            result("https://orion.example/releases", "Orion 4.4 is the latest stable release of the Orion runtime.", 30, "Orion releases", 0.95),
            result("https://devnotes.example/orion", "The latest stable release of the Orion runtime is version 4.2.", 320, "Orion runtime notes", 0.6),
        ],
        "Orion 4.4 release date": [
            result("https://orion.example/blog/orion-4-4", f"Orion 4.4 was released on {long_date(ORION_44_RELEASED)}, with faster startup.", ORION_44_RELEASED, "Orion 4.4 is out", 0.95),
        ],
        "Orion runtime release history": [
            result("https://orion.example/history", f"Release history: Orion 4.2 (March 4, 2025), Orion 4.3 (September 2, 2025), Orion 4.4 ({long_date(ORION_44_RELEASED)}).", 30, "Orion release history", 0.95),
            result("https://orion.example/releases", "Orion 4.4 is the latest stable release of the Orion runtime.", 30, "Orion releases", 0.9),
        ],
        "Acme Cloud Starter plan price history": [
            result("https://acme.example/pricing/history", "Starter plan price history: $8 per month from 2023 to August 2025, $10 per month from September 2025, and $25 per month since this spring.", 4, "Acme price history", 0.95),
        ],
        "Orion runtime end of life versions": [
            result("https://orion.example/lifecycle", "End of life: Orion 1.x, 2.x and 3.x. Supported: Orion 4.x only.", 20, "Orion lifecycle", 0.95),
        ],
    }


FULL_PAGES = {
    "https://nimbus.example/pricing": "Nimbus Cloud Starter plan: $28 per seat per month, up to 5 seats. Team plan: $35 per seat per month.",
}

# What a link check finds at each address: status, redirect target, page text.
LINK_PAGES: dict[str, tuple[int, str | None, str]] = {
    "https://nimbus.example/pricing": (200, None, FULL_PAGES["https://nimbus.example/pricing"]),
    "https://technews.example/nimbus-price": (404, None, "Not found"),
    "https://dailycloud.example/nimbus": (301, "https://dailycloud.example/archive/nimbus", ""),
    "https://dailycloud.example/archive/nimbus": (200, None, "Archive: Nimbus Cloud raises its Starter plan to $28 per seat per month, effective this quarter!"),
    "https://oldblog.example/cheap-clouds": (410, None, "Gone"),
    "https://nimbus.example/docs/changelog": (200, None, "SDK 5.0 release notes. See the migration guide."),
}


def one(eid, stance, quote):
    return {"id": eid, "stance": stance, "quote": quote}


def adjudicate(claim_text: str, context: str) -> Any:
    text = claim_text
    # Claims about June 2025 are judged against June 2025: later releases don't count against them.
    if text.startswith("In June 2025, the latest stable release of the Orion runtime was version"):
        stated = re.search(r"version (\d+\.\d+)", text).group(1)
        stance = "supports" if stated == "4.2" else "contradicts"
        reply = {"judgements": [one("E1", stance, "Orion 4.2 (March 4, 2025), Orion 4.3 (September 2, 2025)"),
                                one("E2", "irrelevant", None)],
                 "current_value": "version 4.2",
                 "explanation": "The release history shows 4.2 was the newest release until 4.3 in September 2025."}
        if stance == "contradicts":
            reply.update(claimed_value=f"version {stated}", change_type="value_changed")
        return reply
    if text.startswith("In June 2025, Acme Cloud's Starter plan cost"):
        return {"judgements": [one("E1", "contradicts", "$8 per month from 2023 to August 2025")],
                "current_value": "$8 per month", "claimed_value": "$10 per month", "change_type": "value_changed",
                "explanation": "The price history shows $8 per month until August 2025; $10 only applied from September 2025."}
    if "Nimbus Cloud's Starter plan costs $28" in text:
        return {"judgements": [one("E1", "supports", "Nimbus Cloud Starter plan: $28 per seat per month"),
                               one("E2", "supports", "raises its Starter plan to $28 per seat per month"),
                               one("E3", "supports", "raises its Starter plan to $28 per seat per month"),
                               one("E4", "irrelevant", None)],
                "current_value": "$28 per seat per month", "change_type": "no_change",
                "explanation": "The official pricing page lists $28 per seat."}
    if "Nimbus Cloud's Starter plan costs" in text:
        return {"judgements": [one("E1", "contradicts", "Nimbus Cloud Starter plan: $28 per seat per month"),
                               one("E2", "contradicts", "raises its Starter plan to $28 per seat per month"),
                               one("E3", "contradicts", "raises its Starter plan to $28 per seat per month"),
                               one("E4", "supports", "Nimbus Cloud's Starter plan costs $20 per seat per month")],
                "current_value": "$28 per seat per month", "claimed_value": "$20 per seat per month",
                "change_type": "value_changed", "explanation": "The official pricing page and the news now list $28 per seat."}
    if "Stratus Cloud charges" in text:
        return {"judgements": [one("E1", "supports", "Stratus Cloud costs $25 per seat per month")],
                "current_value": "$25 per seat per month", "change_type": "no_change",
                "explanation": "Stratus's pricing page still lists $25 per seat."}
    if "available in" in text and "Nimbus" in text:
        note = "No Brazil region is listed." if "Brazil" in context else None
        return {"judgements": [one("E1", "supports", "Nimbus Cloud regions: Mumbai (India)")],
                "current_value": "Available in India (Mumbai region)", "context_note": note,
                "explanation": "Nimbus lists a Mumbai region."}
    if "nimbus.deployments.create" in text:
        return {"judgements": [one("E1", "supports", "Use nimbus.deployments.create(app) instead")],
                "current_value": "nimbus.deployments.create(app)", "change_type": "no_change",
                "explanation": "The SDK changelog names this as the way to deploy."}
    if "allows up to 5 seats" in text:
        return {"judgements": [one("E1", "supports", "The Starter plan supports up to 5 seats")],
                "current_value": "Up to 5 seats", "explanation": "The plans page lists a 5-seat cap."}
    if "Orion runtime is version" in text:
        if "4.4" in text:
            return {"judgements": [one("E1", "supports", "Orion 4.4 is the latest stable release of the Orion runtime"),
                                   one("E2", "irrelevant", None)],
                    "current_value": "version 4.4", "explanation": "The release page lists 4.4 as the latest."}
        return {"judgements": [one("E1", "contradicts", "Orion 4.4 is the latest stable release of the Orion runtime"),
                               one("E2", "supports", "The latest stable release of the Orion runtime is version 4.2")],
                "current_value": "version 4.4", "claimed_value": "version 4.2", "change_type": "superseded",
                "explanation": "The official release page lists Orion 4.4 as the latest stable release."}
    if "Orion 4.4 was launched on" in text:
        released = long_date(ORION_44_RELEASED)
        stance = "supports" if released in text else "contradicts"
        reply = {"judgements": [one("E1", stance, f"Orion 4.4 was released on {released}")],
                 "current_value": released, "explanation": "The Orion blog gives the 4.4 release date."}
        if stance == "contradicts":
            reply.update(claimed_value=re.search(r"launched on (.+?)\.?$", text).group(1), change_type="value_changed")
        return reply
    if "no longer receive support" in text:
        if "3.x" in text:
            return {"judgements": [one("E1", "supports", "End of life: Orion 1.x, 2.x and 3.x")],
                    "current_value": "1.x, 2.x and 3.x", "explanation": "The lifecycle page agrees."}
        return {"judgements": [one("E1", "contradicts", "End of life: Orion 1.x, 2.x and 3.x")],
                "current_value": "1.x, 2.x and 3.x", "claimed_value": "1.x and 2.x", "change_type": "value_changed",
                "explanation": "The lifecycle page now lists 3.x as end of life too."}
    if "nimbus.deploy" in text:
        return {"judgements": [one("E1", "contradicts", "nimbus.deploy() is deprecated. Use nimbus.deployments.create(app) instead")],
                "current_value": "nimbus.deployments.create(app)", "claimed_value": "nimbus.deploy(app)",
                "change_type": "deprecated", "explanation": "The SDK changelog deprecates nimbus.deploy()."}
    if "at least 10 seats" in text:
        return {"judgements": [one("E1", "contradicts", "The Starter plan supports up to 5 seats")],
                "current_value": "Up to 5 seats", "claimed_value": "at least 10 seats",
                "change_type": "value_changed", "explanation": "The Starter plan is capped at 5 seats."}
    if "Acme Cloud costs" in text:
        return {"judgements": [one("E1", "contradicts", "Starter plan now costs $25 per month"),
                               one("E2", "contradicts", "raised its Starter plan to $25 per month"),
                               one("E3", "supports", "Acme Cloud costs $10 per month")],
                "current_value": "$25 per month", "claimed_value": "$10 per month",
                "change_type": "value_changed", "explanation": "Current sources list a higher Starter price."}
    if "Acme SDK" in text:
        return {"judgements": [one("E1", "supports", "latest Acme SDK is version 3.2")],
                "current_value": "Version 3.2", "explanation": "The only source agrees, but it is several months old."}
    if "CEO" in text:
        return {"judgements": [one("E1", "supports", "Bo Lee is the chief executive of Acme"),
                               one("E2", "supports", "Acme CEO Bo Lee")],
                "current_value": "Bo Lee", "explanation": "The company site and trade press agree."}
    if "40 million" in text:
        return {"judgements": [one("E1", "supports", "Acme has 40 million users")],
                "current_value": "40 million", "explanation": "Only a forum post mentions this."}
    if "Orbit" in text:
        return "this is not valid JSON"
    if "Data Act" in text:
        return {"judgements": [one("E1", "supports", "requires companies to keep records for 5 years")],
                "current_value": "5 years", "explanation": "The government source confirms the period."}
    if "spring sale" in text:
        return {"judgements": [one("E1", "supports", "The Acme spring sale is running now")],
                "current_value": "Running", "explanation": "The sale page says it is running."}
    if "users per workspace" in text:
        match = re.search(r"up to ([\d,]+) users", text)
        stated = match.group(1) if match else ""
        if stated == "8,000":
            return {"judgements": [one("E1", "supports", "supports up to 8,000 users")],
                    "current_value": "8,000 users", "explanation": "The limits page lists 8,000 users."}
        return {"judgements": [one("E1", "contradicts", "supports up to 8,000 users")],
                "current_value": "8,000 users", "claimed_value": f"{stated} users",
                "change_type": "value_changed", "explanation": "The limits page lists 8,000 users."}
    if "Acme Vault costs" in text:
        if "$15" in text:
            return {"judgements": [one("E1", "supports", "Acme Vault costs $15 per user per month")],
                    "current_value": "$15 per user per month", "explanation": "The pricing page agrees."}
        return {"judgements": [one("E1", "contradicts", "Acme Vault costs $15 per user per month")],
                "current_value": "$15 per user per month", "claimed_value": re.search(r"\$\d+ per user per month", text).group(),
                "change_type": "value_changed", "explanation": "The pricing page lists $15."}
    return {"judgements": [], "current_value": None, "explanation": "No source states a value for this claim."}


def extraction_for(answer: str) -> list[dict]:
    if answer == CLOUD_ANSWER:
        return CLOUD_EXTRACTION
    if answer == RELEASE_ANSWER:
        return RELEASE_EXTRACTION
    if answer == HISTORY_ANSWER:
        return HISTORY_EXTRACTION
    if "Acme Vault" in answer:
        return vault_extraction(answer)
    if "Acme Cloud costs" in answer:
        return FACTS_EXTRACTION
    return document_extraction(answer)


def retarget_reply(full: str) -> dict:
    """Restate each detail about the current value, by swapping the version number."""
    items = []
    pattern = r'<item id="(c\d+)">\nvalue claim: .*?\nvalue as stated: (.*?)\ncurrent value: (.*?)\ndetail claim: (.*?)\n</item>'
    for cid, stated, current, detail in re.findall(pattern, full, re.S):
        old, new = _NUMBER.search(stated), _NUMBER.search(current)
        if not old or not new or old.group() not in detail:
            items.append({"id": cid, "transfers": False, "text": "", "search_queries": []})
            continue
        text = detail.replace(old.group(), new.group())
        subject = text.split(" was ")[0] if " was " in text else text
        items.append({"id": cid, "transfers": True, "text": text, "search_queries": [f"{subject} release date"]})
    return {"items": items}


def generated_answer(question: str) -> str:
    lowered = question.lower()
    if any(word in lowered for word in ("cloud host", "nimbus", "deploy")):
        return CLOUD_ANSWER
    if "vault" in lowered:
        return VAULT_ANSWERS[0]["answer"]
    return FACTS_ANSWER


_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def rewrite_passage(original: str, current: str) -> str:
    if "fits the Starter plan" in original:
        return "the Starter plan now allows up to 5 seats, so your team of 10 needs the Team plan"
    if "cheapest option" in original:
        return "Stratus Cloud is now the cheaper option, at $25 per seat per month"
    if current.startswith("-") and _NUMBER.search(original):
        return f"costing you ${current.lstrip('-$')} more a month"
    old_number = _NUMBER.search(original)
    new_number = _NUMBER.search(current)
    if old_number and new_number and "seat" not in current.lower()[:3]:
        return original[: old_number.start()] + new_number.group() + original[old_number.end():]
    code = re.search(r"[\w.]+\(\w*\)", original)
    if code and "(" in current:
        return original[: code.start()] + current + original[code.end():]
    return current


def rewrite_reply(full: str) -> list[dict]:
    """One replacement per passage: each stated value swapped for its current one."""
    replies = []
    for cid, body in re.findall(r'<passage id="([\w-]+)">\n(.*?)\n</passage>', full, re.S):
        lines = body.split("\n")
        original = lines[0].removeprefix("original: ")
        facts = [re.match(r"fact: .*?(?: \| stated: (.*?))? \| (?:now|value at that time \(.*?\)): (.*)$", line)
                 for line in lines[1:]]
        facts = [fact for fact in facts if fact]
        text = original
        for fact in facts:
            stated, now = fact.groups()
            if now.startswith(("keep unchanged", "unknown")):
                continue
            if stated and stated in text:
                text = text.replace(stated, now, 1)
            else:
                text = rewrite_passage(text, now)
        replies.append({"claim_id": cid, "replacement": text})
    return replies


def decision_reply() -> dict:
    return {
        "holds": "no",
        "revised": "Stratus Cloud is now the cheaper option for a 10-person startup, at $25 per seat per month.",
        "reason": "Nimbus Cloud's Starter plan now costs $28 per seat and allows only 5 seats.",
    }


# --- the transport ------------------------------------------------------------


class Simulator:
    """An httpx handler that plays Bifrost, Tavily and the web."""

    def __init__(self, latency: tuple[float, float] = (0.15, 0.5)) -> None:
        self.latency = latency
        self.cache: set[tuple] = set()
        self.spend = 0.0
        self.credits = 0
        self.searches = search_results()

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.latency[1] > 0:
            await asyncio.sleep(random.uniform(*self.latency))
        url = str(request.url).split("?")[0]
        path = request.url.path
        if request.url.host == "api.tavily.com":
            return self._tavily(path, request)
        if url in LINK_PAGES or request.url.host.endswith(".example"):
            return self._web(url)
        return self._bifrost(path, request)

    def _web(self, url: str) -> httpx.Response:
        # Pages without a link fixture still say what their search result said.
        snippets = [item["content"] for items in search_results().values() for item in items if item["url"] == url]
        status, location, text = LINK_PAGES.get(url, (200, None, " ".join(snippets) or "A page in the demo web."))
        headers = {"location": location} if location else {}
        return httpx.Response(status, headers=headers, text=text)

    def _tavily(self, path: str, request: httpx.Request) -> httpx.Response:
        if path == "/usage":
            return httpx.Response(200, json={"key": {"usage": self.credits, "limit": 1000}})
        body = json.loads(request.content)
        if path == "/extract":
            results = [{"url": u, "raw_content": FULL_PAGES[u]} for u in body["urls"] if u in FULL_PAGES]
            self.credits += 1 if results else 0
            return httpx.Response(200, json={"results": results, "usage": {"credits": 1 if results else 0}})
        query = re.sub(r" (India|Brazil|[A-Z][a-z]+ [A-Z][a-z]+)$", "", body["query"])
        found = self.searches.get(query) or self.searches.get(body["query"], [])
        self.credits += 1
        return httpx.Response(200, json={"results": found, "usage": {"credits": 1}})

    def _bifrost(self, path: str, request: httpx.Request) -> httpx.Response:
        if path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if path == "/api/session/is-auth-enabled":
            return httpx.Response(200, json={"inference_auth_enforced": False})
        if path == "/api/governance/virtual-keys/quota":
            return httpx.Response(200, json={"virtual_key_name": "shelflife-workspace", "is_active": True,
                                             "budgets": [{"max_limit": 5.0, "current_usage": round(self.spend, 4), "reset_duration": "1M"}]})
        if path.startswith("/api/plugins"):
            return httpx.Response(200, json={"plugins": [{"name": "semantic_cache", "enabled": True}]})
        body = json.loads(request.content)
        messages = body["messages"]
        full = "\n".join(message["content"] for message in messages)
        last = messages[-1]["content"]
        context = (re.search(r"<context>\n(.*?)\n</context>", full, re.S) or [None, ""])[1] or ""

        if "<passage" in full:
            reply: Any = {"replacements": rewrite_reply(full)}
        elif "<item id=" in full:
            reply = retarget_reply(full)
        elif "<recommendation>" in full:
            reply = decision_reply()
        elif (match := re.search(r"<claim>\n(.*?)\n</claim>", full, re.S)):
            reply = adjudicate(match.group(1), context)
        elif "<answer>" in last:
            answer = re.search(r"<answer>\n(.*?)\n</answer>", last, re.S).group(1)
            reply = {"claims": extraction_for(answer)}
        else:
            question = re.search(r"<question>\n(.*?)\n</question>", full, re.S)
            reply = generated_answer(question.group(1) if question else last)
        content = reply if isinstance(reply, str) else json.dumps(reply)

        provider, model = body["model"].split("/", 1)
        cache_key = request.headers.get("x-bf-cache-key")
        fingerprint = (cache_key, body["model"], full)
        if cache_key and fingerprint in self.cache:
            return self._completion(content, {"provider": provider, "model": model},
                                    {"cache_hit": True, "hit_type": "direct"}, cost=None)
        if cache_key:
            self.cache.add(fingerprint)
        routing = {"provider": provider, "model": model}
        # Runs with the cache off stand in for a broken primary provider.
        if not cache_key and body.get("fallbacks"):
            fallback_provider, fallback_model = body["fallbacks"][0].split("/", 1)
            routing = {"provider": fallback_provider, "model": fallback_model, "is_fallback": True,
                       "primary_provider": provider, "primary_model": model}
        self.spend += 0.00042
        return self._completion(content, routing, {"cache_hit": False}, cost=0.00042)

    @staticmethod
    def _completion(content: str, routing: dict, cache: dict, cost: float | None) -> httpx.Response:
        usage = {"prompt_tokens": 820, "completion_tokens": 90, "total_tokens": 910}
        if cost is not None:
            usage["cost"] = {"total_cost": cost}
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": usage,
            "extra_fields": {"routing_info": routing, "cache_debug": cache},
        })
