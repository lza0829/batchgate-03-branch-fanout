from __future__ import annotations

from typing import Any

from app.config import FIXTURES_DIR
from app.db import connect
from app.engines.branching import evaluate_conditions
from app.engines.dependency import ready_by_upstream_success, topological_layers
from app.engines.job_runner import run_fixture_job
from app.repositories import jobs as jobs_repo
from app.repositories import orchestrations as orch_repo
from app.repositories import watermarks as wm_repo

# Distinct terminal statuses. skipped_* are never collapsed into one bucket:
# - skipped_dep:    a depends_on edge was not satisfied (upstream failed/skipped)
# - skipped_branch: dependencies were ready, but the declared branch condition
#                   evaluated false against actual upstream output (bypass,
#                   fixture never runs)
# - skipped_mutex:  branch was selected but its mutex group was already claimed
ATTEMPT_STATUSES = (
    "success",
    "failed",
    "skipped_dep",
    "skipped_branch",
    "skipped_mutex",
)


def dashboard_stats() -> dict[str, Any]:
    conn = connect()
    try:
        return {
            "job_count": conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"],
            "enabled_jobs": conn.execute(
                "SELECT COUNT(*) c FROM jobs WHERE enabled=1"
            ).fetchone()["c"],
            "orchestration_count": conn.execute(
                "SELECT COUNT(*) c FROM orchestrations"
            ).fetchone()["c"],
            "attempt_count": conn.execute(
                "SELECT COUNT(*) c FROM job_attempts"
            ).fetchone()["c"],
            "watermarked_jobs": conn.execute(
                "SELECT COUNT(*) c FROM watermarks WHERE watermark_ts IS NOT NULL"
            ).fetchone()["c"],
        }
    finally:
        conn.close()


def _record(
    conn,
    *,
    orch_id: int,
    job: dict[str, Any],
    status: str,
    detail: dict[str, Any],
) -> None:
    orch_repo.insert_attempt(
        conn,
        orchestration_id=orch_id,
        job_id=job["id"],
        attempt_no=1,
        status=status,
        detail=detail,
    )


def run_orchestration() -> dict[str, Any]:
    conn = connect()
    try:
        result = _run_orchestration(conn)
    finally:
        conn.close()
    return result


def _run_orchestration(conn) -> dict[str, Any]:
    jobs = [j for j in jobs_repo.list_jobs(conn) if j["enabled"]]
    orch_id = orch_repo.create_orchestration(conn)
    # name -> successful attempt detail (artifact_rows / flags / watermark...)
    outputs: dict[str, dict[str, Any]] = {}
    # mutex group -> name of the job that claimed it this run
    mutex_claimed: dict[str, str] = {}
    layers = topological_layers(jobs)

    for layer in layers:
        for job in layer:
            name = job["name"]

            # 1) dependency readiness — edge-level gate, not a branch condition
            ready, reason = ready_by_upstream_success(job["depends_on"], set(outputs))
            if not ready:
                _record(
                    conn,
                    orch_id=orch_id,
                    job=job,
                    status="skipped_dep",
                    detail={
                        "reason": reason,
                        "depends_on": job["depends_on"],
                    },
                )
                continue

            # 2) conditional branch — bypass without ever touching the fixture
            conditions = job["branch_conditions"] or []
            met, reason = evaluate_conditions(conditions, outputs)
            if not met:
                _record(
                    conn,
                    orch_id=orch_id,
                    job=job,
                    status="skipped_branch",
                    detail={
                        "reason": reason,
                        "branch_conditions": conditions,
                    },
                )
                continue

            # 3) mutual exclusion — at most one selected member per group/run
            group = job.get("mutex_group")
            if group and group in mutex_claimed:
                _record(
                    conn,
                    orch_id=orch_id,
                    job=job,
                    status="skipped_mutex",
                    detail={
                        "reason": (
                            f"互斥组 {group} 已被 {mutex_claimed[group]} 占用，"
                            "同一编排内互斥下游只允许一个执行"
                        ),
                        "mutex_group": group,
                        "claimed_by": mutex_claimed[group],
                    },
                )
                continue

            # 4) execute the fixture; claim the mutex slot at selection time so
            #    a failing winner still prevents alternative branches running.
            if group:
                mutex_claimed[group] = name
            try:
                result = run_fixture_job(FIXTURES_DIR / job["fixture_path"])
                _record(
                    conn,
                    orch_id=orch_id,
                    job=job,
                    status="success",
                    detail=result,
                )
                # watermark only advances for jobs that actually ran successfully
                wm_repo.set_watermark(
                    conn, job["id"], result["watermark_ts"], result["artifact_rows"]
                )
                outputs[name] = result
            except Exception as exc:  # noqa: BLE001
                _record(
                    conn,
                    orch_id=orch_id,
                    job=job,
                    status="failed",
                    detail={"error": str(exc)},
                )

    # Derive every report number from the persisted attempts so the report can
    # never disagree with the attempt list ("对上" by construction).
    attempts = orch_repo.list_attempts(conn, orch_id)
    counts = {status: 0 for status in ATTEMPT_STATUSES}
    job_statuses: list[dict[str, Any]] = []
    for attempt in attempts:
        counts[attempt["status"]] += 1
        entry = {
            "job_name": attempt["job_name"],
            "status": attempt["status"],
        }
        reason = attempt["detail"].get("reason")
        if reason:
            entry["reason"] = reason
        job_statuses.append(entry)

    report = {
        "orchestration_id": orch_id,
        "job_total": len(jobs),
        "succeeded": counts["success"],
        "failed": counts["failed"],
        "skipped_dep": counts["skipped_dep"],
        "skipped_branch": counts["skipped_branch"],
        "skipped_mutex": counts["skipped_mutex"],
        "skipped": counts["skipped_dep"]
        + counts["skipped_branch"]
        + counts["skipped_mutex"],
        "attempt_count": len(attempts),
        "watermarked_jobs": conn.execute(
            "SELECT COUNT(*) c FROM watermarks WHERE watermark_ts IS NOT NULL"
        ).fetchone()["c"],
        "layer_count": len(layers),
        "job_statuses": job_statuses,
    }
    # structural reconciliation: one attempt per enabled job, buckets sum up
    assert report["attempt_count"] == report["job_total"]
    assert (
        report["succeeded"]
        + report["failed"]
        + report["skipped_dep"]
        + report["skipped_branch"]
        + report["skipped_mutex"]
        == report["attempt_count"]
    )
    status = "ok" if report["failed"] == 0 else "partial"
    orch_repo.finish_orchestration(conn, orch_id, status, report)
    conn.commit()
    return orch_repo.get_orchestration(conn, orch_id) or report
