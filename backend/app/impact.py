"""Downstream impact: what an outdated fact can affect.

Finding one stale claim is useful. Knowing everything built on it is worth more.
A price stated by an assistant ends up in a sales proposal, a financial projection
and a customer email; when the price changes, each of those needs updating.

This module keeps that map:

- Documents: outputs built from claims (proposals, emails, reports). Each document's
  claims are extracted and linked to claim passports, by id when the app declares
  which claims it used, and by meaning otherwise.
- The dependency freshness graph: claims that rely on other claims, inside one
  answer (a total relies on a price; a release date describes a version) and across
  answers (an app can declare that a library recommendation relies on a Python
  version, which relies on an operating system release).

When a claim goes stale, `impact_report` walks the graph downstream and lists every
claim, answer and document that may now be wrong, with the path that links them, and
`analyze_document` writes each affected document's corrected version: stale values
replaced, calculations redone, and advice re-judged, with sources.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints

from app import history, llm, workspace
from app.evaluation.matching import similarity
from app.models import DERIVED_KINDS, AnswerText, CheckResult, Claim, ClaimResult
from app.passport import passport_id
from app.pipeline.extract import extract_claims
from app.pipeline.metrics import MetricsCollector
from app.pipeline.reasoning import resolve_derived
from app.pipeline.rewrite import rewrite_answer

logger = logging.getLogger(__name__)

# A document's claim and a checked claim must be this alike to be the same fact.
MATCH_THRESHOLD = 0.75
_CODE = re.compile(r"[A-Za-z_][\w.]*\([^()]*\)")
TRUSTED = ("fresh", "uncertain")
DOCUMENT_KINDS = ("proposal", "projection", "email", "report", "recommendation", "other")

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL,
    original_text TEXT NOT NULL, claims TEXT NOT NULL, declared TEXT NOT NULL,
    source_check_id TEXT, revisions TEXT NOT NULL, analysis TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS claim_edges (
    id TEXT PRIMARY KEY, upstream TEXT NOT NULL, downstream TEXT NOT NULL,
    note TEXT NOT NULL, created_at TEXT NOT NULL);
"""

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
PassportId = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^CLM-[0-9A-F]{6}$")]


class DocumentRequest(BaseModel):
    title: Title
    kind: Literal[DOCUMENT_KINDS] = "other"  # type: ignore[valid-type]
    text: AnswerText
    # The check the document was generated from, if any.
    check_id: str | None = None
    # Claims the generating app says it used, by passport id.
    passport_ids: list[PassportId] = Field(default_factory=list, max_length=50)


class EdgeRequest(BaseModel):
    """`downstream` relies on `upstream`: if upstream changes, downstream may be wrong."""

    upstream: PassportId
    downstream: PassportId
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] = ""


# --- the claim index -----------------------------------------------------------------


@dataclass
class Index:
    """Every checked claim's latest result, and the graph between claims, answers and documents."""

    latest: dict[str, ClaimResult] = field(default_factory=dict)
    checked_at: dict[str, str] = field(default_factory=dict)
    # passport -> check ids of the latest check of each answer that states it.
    answers: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    checks: dict[str, CheckResult] = field(default_factory=dict)
    # upstream passport -> {(downstream passport, relation, note)}
    edges: dict[str, set[tuple[str, str, str]]] = field(default_factory=lambda: defaultdict(set))

    def match(self, claim: Claim) -> str | None:
        """The passport of a checked claim saying the same thing, if there is one."""
        pid = claim.passport_id or passport_id(claim.text)
        if pid in self.latest:
            return pid
        best, best_score = None, 0.0
        for other, result in self.latest.items():
            if not states_same_value(claim.text, result):
                continue
            score = max(
                similarity(claim.text, result.claim.text),
                similarity(claim.text, result.checked_as) if result.checked_as else 0.0,
            )
            if score > best_score:
                best, best_score = other, score
        return best if best_score >= MATCH_THRESHOLD else None


def states_same_value(text: str, result: ClaimResult) -> bool:
    """Whether a claim states the same value as a checked one, rather than a different
    or newer one. Similar wording isn't enough: "nimbus.deployments.create(app) is the
    way to deploy" reads like "nimbus.deploy(app) is the way to deploy", but it states
    the correction, so it must not inherit the old claim's stale verdict."""
    lowered = text.casefold()
    old = (result.change.old_value if result.change else None) or ""
    new = result.current_value or ""
    if result.verdict == "stale" and new and new.casefold() in lowered and old.casefold() not in lowered:
        return False
    codes, other_codes = set(_CODE.findall(text)), set(_CODE.findall(result.claim.text))
    return not (codes and other_codes and not codes & other_codes)


def _checked_on(check: CheckResult) -> str:
    return check.checked_at.isoformat() if check.checked_at else check.check_date.isoformat()


def build_index(checks: list[CheckResult] | None = None) -> Index:
    checks = checks if checks is not None else history.store().recent(500)
    index = Index()
    latest_per_answer: dict[str, CheckResult] = {}
    for check in sorted(checks, key=_checked_on):
        latest_per_answer[history.answer_key(check.answer)] = check
        ids = {item.claim.id: item.claim.passport_id or passport_id(item.claim.text) for item in check.claims}
        for item in check.claims:
            pid = ids[item.claim.id]
            index.latest[pid] = item
            index.checked_at[pid] = _checked_on(check)
            for dep in item.claim.depends_on:
                if dep in ids and ids[dep] != pid:
                    relation = "describes" if item.coupled_to == dep else "relies_on"
                    index.edges[ids[dep]].add((pid, relation, ""))
    for check in latest_per_answer.values():
        index.checks[check.id] = check
        for item in check.claims:
            index.answers[item.claim.passport_id or passport_id(item.claim.text)].add(check.id)
    for edge in list_edges():
        index.edges[edge["upstream"]].add((edge["downstream"], "declared", edge["note"]))
    return index


# --- declared edges between claims -----------------------------------------------------


def list_edges() -> list[dict[str, Any]]:
    return workspace.query("SELECT * FROM claim_edges ORDER BY created_at", schema=SCHEMA)


def add_edge(request: EdgeRequest) -> dict[str, Any]:
    if request.upstream == request.downstream:
        raise ValueError("A claim can't depend on itself.")
    if _reaches(request.downstream, request.upstream):
        raise ValueError("That would make a cycle: the upstream claim already depends on the downstream one.")
    edge_id = workspace.new_id()
    workspace.execute(
        "INSERT INTO claim_edges VALUES (?, ?, ?, ?, ?)",
        (edge_id, request.upstream, request.downstream, request.note, workspace.now()),
        schema=SCHEMA,
    )
    return {"id": edge_id, **request.model_dump()}


def delete_edge(edge_id: str) -> None:
    workspace.execute("DELETE FROM claim_edges WHERE id = ?", (edge_id,), schema=SCHEMA)


def _reaches(start: str, goal: str) -> bool:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in list_edges():
        adjacency[edge["upstream"]].add(edge["downstream"])
    seen, queue = {start}, deque([start])
    while queue:
        node = queue.popleft()
        if node == goal:
            return True
        for nxt in adjacency[node] - seen:
            seen.add(nxt)
            queue.append(nxt)
    return False


# --- documents -------------------------------------------------------------------------


def _document(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **row,
        "claims": [Claim.model_validate(item) for item in json.loads(row["claims"])],
        "declared": json.loads(row["declared"]),
        "revisions": json.loads(row["revisions"]),
        "analysis": json.loads(row["analysis"]) if row.get("analysis") else None,
    }


def list_documents() -> list[dict[str, Any]]:
    return [_document(row) for row in workspace.query(
        "SELECT * FROM documents ORDER BY created_at", schema=SCHEMA
    )]


def get_document(document_id: str) -> dict[str, Any] | None:
    rows = workspace.query("SELECT * FROM documents WHERE id = ?", (document_id,), schema=SCHEMA)
    return _document(rows[0]) if rows else None


def delete_document(document_id: str) -> None:
    workspace.execute("DELETE FROM documents WHERE id = ?", (document_id,), schema=SCHEMA)


async def _extract(text: str) -> list[Claim]:
    """The document's claims, located in its text. A model failure leaves it unlinked."""
    try:
        return await extract_claims(text, None, None, date.today(), MetricsCollector())
    except llm.LLMError:
        logger.warning("Could not extract the claims of a document")
        return []


async def register_document(request: DocumentRequest) -> dict[str, Any]:
    claims = await _extract(request.text)
    declared = list(dict.fromkeys(request.passport_ids))
    if request.check_id:
        source = history.store().get(request.check_id)
        if source is None:
            raise KeyError(request.check_id)
    document_id = workspace.new_id()
    stamp = workspace.now()
    workspace.execute(
        "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            document_id, request.title, request.kind, request.text, request.text,
            json.dumps([claim.model_dump(mode="json") for claim in claims]), json.dumps(declared),
            request.check_id, "[]", None, stamp, stamp,
        ),
        schema=SCHEMA,
    )
    return get_document(document_id)


async def apply_correction(document_id: str, by: str) -> dict[str, Any] | None:
    """Replace the document's text with its corrected version, keeping the old one."""
    document = get_document(document_id)
    if document is None:
        return None
    analysis = await analyze_document(document)
    corrected = analysis["corrected_text"]
    if not analysis["stale"] or corrected == document["text"]:
        return document
    changes = [
        {
            "claim": link["text"],
            "old": link["claimed_value"],
            # A recommendation with no safe rewording is marked rather than replaced.
            "new": link["current_value"] or ("no longer holds" if link["kind"] == "recommendation" else "out of date"),
        }
        for link in analysis["links"]
        if link["status"] == "stale"
    ]
    # The same correction twice in a row means the first one didn't take: stop
    # rather than stack another "(now ...)" onto the text.
    if document["revisions"] and document["revisions"][-1]["changes"] == changes:
        logger.warning("Skipped a repeated correction of document %s", document_id)
        return document
    revisions = [*document["revisions"], {
        "at": workspace.now(), "by": by, "previous_text": document["text"], "changes": changes,
    }]
    claims = await _extract(corrected)
    workspace.execute(
        "UPDATE documents SET text = ?, claims = ?, revisions = ?, analysis = NULL, updated_at = ? WHERE id = ?",
        (corrected, json.dumps([c.model_dump(mode="json") for c in claims]), json.dumps(revisions),
         workspace.now(), document_id),
        schema=SCHEMA,
    )
    return get_document(document_id)


def _linked_result(claim: Claim, matched: ClaimResult) -> ClaimResult:
    """The matched claim's verdict and evidence, placed at this claim in the document."""
    return matched.model_copy(update={
        "claim": claim.model_copy(update={"passport_id": matched.claim.passport_id}),
        "affected_by": [],
        "recalculation": None,
        "decision": None,
        "coupled_to": None,
    })


def _unchecked(claim: Claim, verdict: str, explanation: str) -> ClaimResult:
    return ClaimResult(
        claim=claim, verdict=verdict, freshness_score=None, confidence=0.0,
        current_value=None, explanation=explanation, evidence=[],
    )


def _analysis_key(document: dict[str, Any], links: list[tuple[str, str | None, ClaimResult | None]]) -> str:
    payload = [document["text"], [
        [claim_id, pid, result.verdict if result else None, result.current_value if result else None]
        for claim_id, pid, result in links
    ], sorted(document["declared"])]
    return hashlib.sha256(json.dumps(payload).encode()).hexdigest()[:16]


async def analyze_document(document: dict[str, Any], index: Index | None = None) -> dict[str, Any]:
    """Each of the document's claims, its freshness, and the corrected document.

    Facts take the verdict of the checked claim they match. Calculations are redone
    and recommendations re-judged from those, and stale passages are rewritten. The
    result is cached until the document or a linked claim's verdict changes.
    """
    index = index or build_index()
    text: str = document["text"]
    claims: list[Claim] = document["claims"]
    matches = [
        (claim.id, None if claim.kind in DERIVED_KINDS else index.match(claim), claim)
        for claim in claims
    ]
    key = _analysis_key(document, [(cid, pid, index.latest.get(pid) if pid else None) for cid, pid, _ in matches])
    cached = document.get("analysis")
    if cached and cached.get("key") == key:
        return cached

    results: dict[str, ClaimResult] = {}
    unchecked_ids: set[str] = set()
    for claim_id, pid, claim in matches:
        if claim.kind in DERIVED_KINDS:
            continue
        if pid:
            results[claim_id] = _linked_result(claim, index.latest[pid])
        elif claim.category == "static" or not claim.time_sensitive:
            results[claim_id] = _unchecked(claim, "not_time_sensitive", "This fact doesn't change over time.")
        else:
            # Not checked anywhere yet: neutral until it is, so it's neither trusted nor flagged.
            results[claim_id] = _unchecked(claim, "uncertain", "Not verified yet.")
            unchecked_ids.add(claim_id)

    metrics = MetricsCollector()
    await resolve_derived(claims, text, results, metrics)
    # Claims the app declared it used, whether or not the text states them word for word.
    declared_results = [
        index.latest[pid].model_copy(update={
            "claim": index.latest[pid].claim.model_copy(update={"id": f"d{n}", "span": None}),
            "coupled_to": None,
        })
        for n, pid in enumerate(document["declared"], start=1)
        if pid in index.latest
    ]
    ordered = [results[claim.id] for claim in claims if claim.id in results] + declared_results
    rewrite = await rewrite_answer(text, [r for r in ordered if r.verdict == "stale"], date.today(), metrics)

    pid_of = {claim_id: pid for claim_id, pid, _ in matches}
    links = []
    for result in ordered:
        claim = result.claim
        pid = pid_of.get(claim.id) or (claim.passport_id if claim.id.startswith("d") else None)
        links.append({
            "claim_id": claim.id,
            "text": claim.text,
            "kind": claim.kind,
            "span": list(claim.span) if claim.span else None,
            "passport_id": pid,
            "declared": claim.id.startswith("d"),
            "status": "unchecked" if claim.id in unchecked_ids else result.verdict,
            "claimed_value": result.change.old_value if result.change else None,
            "current_value": result.current_value,
            "explanation": result.explanation,
            "checked_at": index.checked_at.get(pid) if pid else None,
        })
    stale = [link for link in links if link["status"] == "stale"]
    unchecked = [link for link in links if link["status"] == "unchecked"]
    analysis = {
        "key": key,
        "status": "needs_update" if stale else ("unverified" if unchecked else "current"),
        "links": links,
        "stale": len(stale),
        "unchecked": len(unchecked),
        "corrected_text": rewrite.corrected_answer,
        "edits": [edit.model_dump(mode="json") for edit in rewrite.edits],
        "citations": [citation.model_dump(mode="json") for citation in rewrite.citations],
        "analyzed_at": workspace.now(),
    }
    workspace.execute(
        "UPDATE documents SET analysis = ? WHERE id = ?",
        (json.dumps(analysis), document["id"]),
        schema=SCHEMA,
    )
    return analysis


def quick_status(document: dict[str, Any], index: Index) -> str:
    """The document's status without any model call: from its cached analysis when it
    is still valid, otherwise from its claims' matches alone."""
    stale = unchecked = False
    for claim in document["claims"]:
        if claim.kind in DERIVED_KINDS:
            continue
        pid = index.match(claim)
        if pid:
            stale = stale or index.latest[pid].verdict == "stale"
        elif claim.time_sensitive and claim.category != "static":
            unchecked = True
    stale = stale or any(
        index.latest[pid].verdict == "stale" for pid in document["declared"] if pid in index.latest
    )
    return "needs_update" if stale else ("unverified" if unchecked else "current")


def document_view(document: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": document["id"],
        "title": document["title"],
        "kind": document["kind"],
        "text": document["text"],
        "original_text": document["original_text"],
        "source_check_id": document["source_check_id"],
        "declared": document["declared"],
        "revisions": document["revisions"],
        "created_at": document["created_at"],
        "updated_at": document["updated_at"],
        **{key: value for key, value in analysis.items() if key != "key"},
    }


# --- impact ------------------------------------------------------------------------------


def _document_uses(index: Index) -> dict[str, list[dict[str, Any]]]:
    """passport -> documents that use it, with the passage."""
    uses: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for document in list_documents():
        for claim in document["claims"]:
            pid = None if claim.kind in DERIVED_KINDS else index.match(claim)
            if pid:
                excerpt = document["text"][slice(*claim.span)] if claim.span else claim.text
                uses[pid].append({"id": document["id"], "title": document["title"],
                                  "kind": document["kind"], "excerpt": excerpt, "declared": False})
        for pid in document["declared"]:
            uses[pid].append({"id": document["id"], "title": document["title"],
                              "kind": document["kind"], "excerpt": None, "declared": True})
    return uses


def _summary(pid: str, index: Index) -> dict[str, Any]:
    result = index.latest.get(pid)
    if result is None:
        return {"passport_id": pid, "text": None, "status": "unknown"}
    return {
        "passport_id": pid,
        "text": result.claim.text,
        "checked_as": result.checked_as,
        "kind": result.claim.kind,
        "category": result.claim.category,
        "status": result.verdict,
        "current_value": result.current_value,
        "change": result.change.model_dump(mode="json") if result.change else None,
        "last_checked": index.checked_at.get(pid),
    }


def impact_report(pid: str, index: Index | None = None, uses: dict | None = None) -> dict[str, Any] | None:
    """Everything downstream of a claim: dependent claims, answers and documents."""
    index = index or build_index()
    if pid not in index.latest and pid not in index.edges:
        return None
    uses = uses if uses is not None else _document_uses(index)
    claims: list[dict[str, Any]] = []
    paths: dict[str, list[str]] = {pid: [pid]}
    queue = deque([pid])
    while queue:
        node = queue.popleft()
        for downstream, relation, note in sorted(index.edges.get(node, ())):
            if downstream in paths:
                continue
            paths[downstream] = [*paths[node], downstream]
            queue.append(downstream)
            claims.append({**_summary(downstream, index), "relation": relation, "note": note,
                           "via": node, "depth": len(paths[downstream]) - 1, "path": paths[downstream]})

    documents: dict[str, dict[str, Any]] = {}
    answers: dict[str, dict[str, Any]] = {}
    for node, path in paths.items():
        for use in uses.get(node, []):
            entry = documents.setdefault(use["id"], {**use, "via": node, "direct": node == pid,
                                                      "depth": len(path) - 1, "passages": []})
            if use["excerpt"] and use["excerpt"] not in entry["passages"]:
                entry["passages"].append(use["excerpt"])
        for check_id in index.answers.get(node, ()):
            check = index.checks[check_id]
            answers.setdefault(check_id, {
                "check_id": check_id, "question": check.question,
                "answer_excerpt": " ".join(check.answer.split())[:140],
                "checked_at": _checked_on(check), "via": node, "direct": node == pid,
                "guard": check.guard.action if check.guard else None,
            })

    root = _summary(pid, index)
    affected = len(claims) + len(documents) + len(answers)
    severity = (
        "none" if root["status"] != "stale"
        else "high" if documents or any(c["kind"] == "recommendation" for c in claims)
        else "medium" if claims or len(answers) > 1
        else "low"
    )
    return {
        "claim": root,
        "severity": severity,
        "dependents": claims,
        "documents": sorted(documents.values(), key=lambda d: (d["depth"], d["title"])),
        "answers": sorted(answers.values(), key=lambda a: a["checked_at"], reverse=True),
        "counts": {"claims": len(claims), "documents": len(documents), "answers": len(answers), "total": affected},
    }


def stale_impacts(index: Index | None = None) -> list[dict[str, Any]]:
    """Every stale claim with what it affects, the biggest blast radius first."""
    index = index or build_index()
    uses = _document_uses(index)
    reports = [
        impact_report(pid, index, uses)
        for pid, result in index.latest.items()
        if result.verdict == "stale"
    ]
    return sorted(
        (report for report in reports if report),
        key=lambda r: (-r["counts"]["documents"], -r["counts"]["total"], r["claim"]["text"] or ""),
    )


def graph(index: Index | None = None, limit: int = 300) -> dict[str, Any]:
    """Nodes and edges for the dependency freshness graph."""
    index = index or build_index()
    uses = _document_uses(index)
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    reach: dict[str, int] = {}

    def downstream_count(pid: str) -> int:
        if pid not in reach:
            report = impact_report(pid, index, uses)
            reach[pid] = report["counts"]["total"] if report else 0
        return reach[pid]

    for pid, result in index.latest.items():
        if result.verdict == "not_time_sensitive" and pid not in index.edges and not uses.get(pid):
            continue
        nodes[pid] = {"id": pid, "type": "claim", "label": result.claim.text, "status": result.verdict,
                      "category": result.claim.category, "kind": result.claim.kind,
                      "current_value": result.current_value}
    for upstream, targets in index.edges.items():
        for downstream, relation, note in targets:
            for pid in (upstream, downstream):
                nodes.setdefault(pid, {"id": pid, "type": "claim", "label": pid, "status": "unknown",
                                       "category": None, "kind": None, "current_value": None})
            edges.append({"source": upstream, "target": downstream, "relation": relation, "note": note})
    for pid, documents in uses.items():
        if pid not in nodes:
            continue
        for use in documents:
            doc_node = f"doc:{use['id']}"
            nodes.setdefault(doc_node, {"id": doc_node, "type": "document", "label": use["title"],
                                        "status": "document", "category": use["kind"], "kind": None,
                                        "current_value": None})
            edge = {"source": pid, "target": doc_node, "relation": "used_in", "note": ""}
            if edge not in edges:
                edges.append(edge)
    for pid in list(nodes):
        if nodes[pid]["type"] == "claim":
            nodes[pid]["reach"] = downstream_count(pid)
            nodes[pid]["answers"] = len(index.answers.get(pid, ()))
    degree: dict[str, int] = defaultdict(int)
    for edge in edges:
        degree[edge["source"]] += 1
        degree[edge["target"]] += 1
    for node in nodes.values():
        node["degree"] = degree[node["id"]]
    ranked = sorted(nodes.values(), key=lambda n: (-(n.get("reach") or 0), -n["degree"]))[:limit]
    kept = {node["id"] for node in ranked}
    hot = [n for n in ranked if n["type"] == "claim" and n.get("reach")][:10]
    return {
        "nodes": ranked,
        "edges": [e for e in edges if e["source"] in kept and e["target"] in kept],
        "hot": hot,
        "stats": {
            "claims": sum(1 for n in nodes.values() if n["type"] == "claim"),
            "documents": sum(1 for n in nodes.values() if n["type"] == "document"),
            "edges": len(edges),
            "stale": sum(1 for n in nodes.values() if n["status"] == "stale"),
            "shown": len(kept),
        },
    }
