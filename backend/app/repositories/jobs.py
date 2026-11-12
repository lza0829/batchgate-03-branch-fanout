from __future__ import annotations

import json
from typing import Any

import sqlite3

_JOB_COLUMNS = (
    "id, name, fixture_path, depends_on_json, max_attempts, enabled, note, "
    "branch_conditions_json, mutex_group"
)


def _row(r: sqlite3.Row | None) -> dict[str, Any] | None:
    if r is None:
        return None
    d = dict(r)
    d["depends_on"] = json.loads(d.pop("depends_on_json"))
    d["branch_conditions"] = json.loads(d.pop("branch_conditions_json") or "[]")
    d["mutex_group"] = d.get("mutex_group")
    d["enabled"] = bool(d["enabled"])
    return d


def list_jobs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(f"SELECT {_JOB_COLUMNS} FROM jobs ORDER BY id").fetchall()
    return [_row(r) for r in rows]  # type: ignore[misc]


def get_job(conn: sqlite3.Connection, job_id: int) -> dict[str, Any] | None:
    r = conn.execute(
        f"SELECT {_JOB_COLUMNS} FROM jobs WHERE id=?",
        (job_id,),
    ).fetchone()
    return _row(r)


def get_job_by_name(conn: sqlite3.Connection, name: str) -> dict[str, Any] | None:
    r = conn.execute(
        f"SELECT {_JOB_COLUMNS} FROM jobs WHERE name=?",
        (name,),
    ).fetchone()
    return _row(r)


def update_max_attempts(conn: sqlite3.Connection, job_id: int, max_attempts: int) -> None:
    conn.execute("UPDATE jobs SET max_attempts=? WHERE id=?", (max_attempts, job_id))


def update_branch_config(
    conn: sqlite3.Connection,
    job_id: int,
    branch_conditions: list[dict[str, Any]],
    mutex_group: str | None,
) -> None:
    conn.execute(
        "UPDATE jobs SET branch_conditions_json=?, mutex_group=? WHERE id=?",
        (
            json.dumps(branch_conditions, ensure_ascii=False),
            mutex_group,
            job_id,
        ),
    )
