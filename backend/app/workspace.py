"""Saved workspace data beside check history: context profiles, regression tests and
comparisons. Everything lives in the same local SQLite file as history.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from typing import Any

from app import config
from app.models import CheckContext

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, context TEXT NOT NULL,
    version INTEGER NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS regression_tests (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, question TEXT NOT NULL, model TEXT,
    must_include TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS regression_runs (
    id TEXT PRIMARY KEY, test_id TEXT NOT NULL, ran_at TEXT NOT NULL, passed INTEGER NOT NULL,
    check_id TEXT, answer TEXT, model TEXT, problems TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS comparisons (
    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, result TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def _connect(schema: str | None = None) -> sqlite3.Connection:
    path = config.get_settings().history_path
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA + (schema or ""))
    return connection


def query(sql: str, params: tuple = (), *, schema: str | None = None) -> list[dict[str, Any]]:
    """Run a query. `schema` lets other modules keep their tables in this database."""
    with closing(_connect(schema)) as connection:
        return [dict(row) for row in connection.execute(sql, params).fetchall()]


def execute(sql: str, params: tuple, *, schema: str | None = None) -> None:
    with closing(_connect(schema)) as connection, connection:
        connection.execute(sql, params)



# --- app settings ------------------------------------------------------------------


def get_setting(key: str, default: Any = None) -> Any:
    found = query("SELECT value FROM app_settings WHERE key = ?", (key,))
    return json.loads(found[0]["value"]) if found else default


def set_setting(key: str, value: Any) -> None:
    execute("INSERT OR REPLACE INTO app_settings VALUES (?, ?)", (key, json.dumps(value)))


# --- context profiles ------------------------------------------------------------


def _profile(row: dict[str, Any]) -> dict[str, Any]:
    return {**row, "context": json.loads(row["context"])}


def list_profiles() -> list[dict[str, Any]]:
    return [_profile(row) for row in query("SELECT * FROM profiles ORDER BY name")]


def get_profile(profile_id: str) -> dict[str, Any] | None:
    rows = query("SELECT * FROM profiles WHERE id = ?", (profile_id,))
    return _profile(rows[0]) if rows else None


def save_profile(name: str, context: CheckContext, profile_id: str | None = None) -> dict[str, Any]:
    """Create a profile, or update one. Changing the context raises its version."""
    existing = get_profile(profile_id) if profile_id else None
    payload = context.model_dump_json()
    if existing is None:
        profile_id = profile_id or new_id()
        execute("INSERT INTO profiles VALUES (?, ?, ?, ?, ?)", (profile_id, name, payload, 1, now()))
    else:
        changed = json.loads(payload) != existing["context"]
        version = existing["version"] + (1 if changed else 0)
        execute(
            "UPDATE profiles SET name = ?, context = ?, version = ?, updated_at = ? WHERE id = ?",
            (name, payload, version, now(), profile_id),
        )
    return get_profile(profile_id)


def delete_profile(profile_id: str) -> None:
    execute("DELETE FROM profiles WHERE id = ?", (profile_id,))


# --- regression tests ----------------------------------------------------------


def _test(row: dict[str, Any]) -> dict[str, Any]:
    return {**row, "must_include": json.loads(row["must_include"])}


def list_tests() -> list[dict[str, Any]]:
    tests = [_test(row) for row in query("SELECT * FROM regression_tests ORDER BY created_at")]
    for test in tests:
        runs = list_runs(test["id"], limit=10)
        test["last_run"] = runs[0] if runs else None
        test["recent"] = [run["passed"] for run in runs]
    return tests


def get_test(test_id: str) -> dict[str, Any] | None:
    rows = query("SELECT * FROM regression_tests WHERE id = ?", (test_id,))
    return _test(rows[0]) if rows else None


def save_test(name: str, question: str, model: str | None, must_include: list[str]) -> dict[str, Any]:
    test_id = new_id()
    execute(
        "INSERT INTO regression_tests VALUES (?, ?, ?, ?, ?, ?)",
        (test_id, name, question, model, json.dumps(must_include), now()),
    )
    return get_test(test_id)


def delete_test(test_id: str) -> None:
    execute("DELETE FROM regression_tests WHERE id = ?", (test_id,))
    execute("DELETE FROM regression_runs WHERE test_id = ?", (test_id,))


def save_run(test_id: str, passed: bool, check_id: str | None, answer: str, model: str, problems: list[str]) -> dict[str, Any]:
    run_id = new_id()
    execute(
        "INSERT INTO regression_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, test_id, now(), int(passed), check_id, answer, model, json.dumps(problems)),
    )
    return list_runs(test_id, limit=1)[0]


def list_runs(test_id: str, limit: int = 20) -> list[dict[str, Any]]:
    rows = query(
        "SELECT * FROM regression_runs WHERE test_id = ? ORDER BY ran_at DESC LIMIT ?", (test_id, limit)
    )
    return [{**row, "passed": bool(row["passed"]), "problems": json.loads(row["problems"])} for row in rows]


# --- comparisons -----------------------------------------------------------------


def save_comparison(result: dict[str, Any]) -> None:
    execute("INSERT OR REPLACE INTO comparisons VALUES (?, ?, ?)", (result["id"], result["created_at"], json.dumps(result)))


def list_comparisons(limit: int = 20) -> list[dict[str, Any]]:
    rows = query("SELECT result FROM comparisons ORDER BY created_at DESC LIMIT ?", (limit,))
    return [json.loads(row["result"]) for row in rows]


def get_comparison(comparison_id: str) -> dict[str, Any] | None:
    rows = query("SELECT result FROM comparisons WHERE id = ?", (comparison_id,))
    return json.loads(rows[0]["result"]) if rows else None
