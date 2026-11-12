"""End-to-end orchestration runs on an isolated temporary SQLite database."""

from __future__ import annotations

import json

import pytest

from app import config
from app.db import connect
from app.repositories import jobs as jobs_repo
from app.repositories import orchestrations as orch_repo
from app.repositories import watermarks as wm_repo
from app.seed import init_db
from app.services.orchestrate_service import _run_orchestration


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    # app.db computes DB_PATH at import time; repoint it explicitly so every
    # connect() call in service code lands on the isolated test database
    from app import db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / config.DB_FILENAME)
    init_db()
    conn = connect()
    yield conn
    conn.close()


def _statuses(orchestration: dict) -> dict[str, str]:
    return {j["job_name"]: j["status"] for j in orchestration["report"]["job_statuses"]}


def test_seed_run_has_all_branch_outcomes_and_reconciles(tmp_db):
    result = _run_orchestration(tmp_db)
    report = result["report"]
    statuses = _statuses(result)

    # flag branch: hit runs fixture, miss is bypassed without a fixture run
    assert statuses["retry_orders"] == "success"
    assert statuses["skip_retry_clean"] == "skipped_branch"

    # row-count threshold: bypass path
    assert statuses["fact_full"] == "skipped_branch"

    # mutex group: both conditions met, only one member executes
    mutex_winners = [
        n
        for n in ("fact_bulk", "fact_recent")
        if statuses[n] == "success"
    ]
    mutex_blocked = [
        n
        for n in ("fact_bulk", "fact_recent")
        if statuses[n] == "skipped_mutex"
    ]
    assert len(mutex_winners) == 1
    assert len(mutex_blocked) == 1

    # unconditional jobs still run
    assert statuses["ingest_orders"] == "success"
    assert statuses["dim_customer"] == "success"
    assert statuses["fact_order_daily"] == "success"

    # report buckets reconcile exactly with persisted attempts
    attempts = orch_repo.list_attempts(tmp_db, result["id"])
    assert len(attempts) == report["job_total"]
    assert (
        report["succeeded"]
        + report["failed"]
        + report["skipped_branch"]
        + report["skipped_mutex"]
        + report["skipped_dep"]
        == report["attempt_count"]
    )
    assert report["skipped_branch"] >= 2
    assert report["skipped_mutex"] == 1
    assert report["failed"] == 0
    assert result["status"] == "ok"

    # bypass attempts carry an auditable reason
    branch_rows = [a for a in attempts if a["status"] == "skipped_branch"]
    assert all(a["detail"].get("reason") for a in branch_rows)

    # watermarks advanced only for actually successful jobs
    wm = {r["job_name"]: r for r in wm_repo.list_watermarks(tmp_db)}
    assert wm["fact_full"]["watermark_ts"] is None
    assert wm["skip_retry_clean"]["watermark_ts"] is None
    assert wm["retry_orders"]["watermark_ts"] == "2026-11-10T18:20:00Z"
    assert wm["retry_orders"]["artifact_rows"] == 2


def test_branch_bypass_is_distinct_from_dependency_skip(tmp_db):
    # break dim_customer so its downstream cannot satisfy depends_on
    dim = jobs_repo.get_job_by_name(tmp_db, "dim_customer")
    tmp_db.execute(
        "UPDATE jobs SET fixture_path=? WHERE id=?",
        ("does_not_exist.json", dim["id"]),
    )
    tmp_db.commit()

    result = _run_orchestration(tmp_db)
    statuses = _statuses(result)

    assert statuses["dim_customer"] == "failed"
    # downstream never reaches branch evaluation: dependency skip, not bypass
    assert statuses["fact_order_daily"] == "skipped_dep"
    assert statuses["fact_bulk"] == "skipped_dep"
    assert statuses["fact_recent"] == "skipped_dep"
    # fact_full only depends on ingest (still successful), so branching applies
    assert statuses["fact_full"] == "skipped_branch"
    # branch-only job whose single upstream still succeeded keeps branching
    assert statuses["skip_retry_clean"] == "skipped_branch"
    assert result["report"]["failed"] == 1
    assert result["report"]["skipped_dep"] == 3
    assert result["status"] == "partial"

    dep_rows = [
        a
        for a in orch_repo.list_attempts(tmp_db, result["id"])
        if a["status"] == "skipped_dep"
    ]
    assert all("upstream not success" in a["detail"]["reason"] for a in dep_rows)
    # failed job must not advance its watermark
    wm = {r["job_name"]: r for r in wm_repo.list_watermarks(tmp_db)}
    assert wm["dim_customer"]["watermark_ts"] is None


def test_configured_row_threshold_hit_runs_and_miss_bypasses(tmp_db):
    # retarget fact_full to a threshold the seed ingest (3 rows) satisfies,
    # exercising the configurable "condition hit -> execute" path
    fact_full = jobs_repo.get_job_by_name(tmp_db, "fact_full")
    jobs_repo.update_branch_config(
        tmp_db,
        fact_full["id"],
        [
            {
                "type": "rows",
                "upstream": "ingest_orders",
                "op": "gte",
                "value": 3,
            }
        ],
        None,
    )
    tmp_db.commit()

    result = _run_orchestration(tmp_db)
    statuses = _statuses(result)
    assert statuses["fact_full"] == "success"
    wm = {r["job_name"]: r for r in wm_repo.list_watermarks(tmp_db)}
    assert wm["fact_full"]["watermark_ts"] == "2026-11-10T19:20:00Z"

    # now push the threshold above the actual row count: bypass, no fixture run
    jobs_repo.update_branch_config(
        tmp_db,
        fact_full["id"],
        [
            {
                "type": "rows",
                "upstream": "ingest_orders",
                "op": "gte",
                "value": 99,
            }
        ],
        None,
    )
    tmp_db.commit()
    result2 = _run_orchestration(tmp_db)
    statuses2 = _statuses(result2)
    assert statuses2["fact_full"] == "skipped_branch"
    wm2 = {r["job_name"]: r for r in wm_repo.list_watermarks(tmp_db)}
    # watermark stays at the previous successful run; bypass does not touch it
    assert wm2["fact_full"]["watermark_ts"] == "2026-11-10T19:20:00Z"


def test_mutex_never_runs_two_members(tmp_db):
    # give every fact_volume member a passing condition and enable a third
    third = jobs_repo.get_job_by_name(tmp_db, "fact_full")
    jobs_repo.update_branch_config(
        tmp_db,
        third["id"],
        [
            {
                "type": "rows",
                "upstream": "ingest_orders",
                "op": "gte",
                "value": 1,
            }
        ],
        "fact_volume",
    )
    tmp_db.commit()

    result = _run_orchestration(tmp_db)
    statuses = _statuses(result)
    members = [statuses["fact_bulk"], statuses["fact_recent"], statuses["fact_full"]]
    assert members.count("success") == 1
    assert members.count("skipped_mutex") == 2

    # mutex detail records who claimed the group
    mutex_rows = [
        a
        for a in orch_repo.list_attempts(tmp_db, result["id"])
        if a["status"] == "skipped_mutex"
    ]
    assert all(a["detail"]["mutex_group"] == "fact_volume" for a in mutex_rows)
    assert all(a["detail"].get("claimed_by") == "fact_bulk" for a in mutex_rows)


def test_branch_config_api_validation(tmp_db):
    from fastapi import HTTPException

    from app.routers.jobs import apply_branch_config
    from app.schemas.entities import BranchConfigBody

    job = jobs_repo.get_job_by_name(tmp_db, "fact_full")

    body = BranchConfigBody(
        branch_conditions=[
            {
                "type": "rows",
                "upstream": "ghost_job",
                "op": "gte",
                "value": 1,
            }
        ],
        mutex_group=None,
    )
    with pytest.raises(HTTPException) as exc:
        apply_branch_config(tmp_db, job["id"], body)
    assert exc.value.status_code == 400

    # valid config is persisted and echoed back
    body_ok = BranchConfigBody(
        branch_conditions=[
            {
                "type": "rows",
                "upstream": "ingest_orders",
                "op": "lte",
                "value": 10,
            }
        ],
        mutex_group="fact_volume",
    )
    updated = apply_branch_config(tmp_db, job["id"], body_ok)
    assert updated["mutex_group"] == "fact_volume"
    assert updated["branch_conditions"][0]["op"] == "lte"
    # the JSON stored in SQLite is itself valid and reloads
    raw = tmp_db.execute(
        "SELECT branch_conditions_json FROM jobs WHERE id=?", (job["id"],)
    ).fetchone()[0]
    assert json.loads(raw)[0]["upstream"] == "ingest_orders"
