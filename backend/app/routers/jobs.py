from fastapi import APIRouter, HTTPException

from app.db import connect
from app.engines.branching import validate_conditions
from app.repositories import jobs as jobs_repo
from app.schemas.entities import BranchConfigBody, MaxAttemptsBody

router = APIRouter(tags=["jobs"])


@router.get("/jobs")
def list_jobs():
    conn = connect()
    try:
        return jobs_repo.list_jobs(conn)
    finally:
        conn.close()


@router.patch("/jobs/{job_id}/max-attempts")
def patch_max_attempts(job_id: int, body: MaxAttemptsBody):
    conn = connect()
    try:
        job = jobs_repo.get_job(conn, job_id)
        if not job:
            raise HTTPException(404, "job not found")
        jobs_repo.update_max_attempts(conn, job_id, body.max_attempts)
        conn.commit()
        return jobs_repo.get_job(conn, job_id)
    finally:
        conn.close()


def apply_branch_config(conn, job_id: int, body: BranchConfigBody) -> dict:
    """Validate and persist branch configuration. Split out so tests can
    supply an explicit connection; the HTTP route owns its own."""
    job = jobs_repo.get_job(conn, job_id)
    if not job:
        raise HTTPException(404, "job not found")
    conditions = [c.model_dump() for c in body.branch_conditions]
    try:
        validate_conditions(conditions, job["depends_on"])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    jobs_repo.update_branch_config(conn, job_id, conditions, body.mutex_group)
    conn.commit()
    return jobs_repo.get_job(conn, job_id)


@router.put("/jobs/{job_id}/branch-config")
def put_branch_config(job_id: int, body: BranchConfigBody):
    conn = connect()
    try:
        return apply_branch_config(conn, job_id, body)
    finally:
        conn.close()
