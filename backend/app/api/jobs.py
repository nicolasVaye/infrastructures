"""Job endpoints: submit, follow, cancel; plus schedule management.

POST /jobs answers 202 Accepted with the created job — execution happens
asynchronously on the worker fleet. This is the "action" entrypoint used by
both the frontend and external automations.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from app.core.db import JobRecord, ScheduleRecord, utcnow
from app.core.security import AdminUser, CurrentUser, DbSession
from app.events import notify_event
from app.services import record
from shared.enums import AuditAction, JobStatus
from shared.models import JobCreate, JobOut, ScheduleCreate, ScheduleOut

router = APIRouter(tags=["jobs"])


@router.post("/jobs", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
async def submit_job(body: JobCreate, user: CurrentUser, session: DbSession) -> JobOut:
    """Submit an action for asynchronous execution. Returns immediately."""
    job = JobRecord(
        job_type=body.job_type,
        params=body.params,
        priority=body.priority,
        created_by=body.created_by or user.username,
        status=JobStatus.QUEUED,
    )
    session.add(job)
    await session.flush()
    await record(session, AuditAction.JOB_SUBMITTED, user_id=user.id,
                 username=user.username, target=body.job_type, details=f"job #{job.id}")
    await notify_event(session, "job_updated", job_id=job.id, status=job.status)
    return JobOut.model_validate(job)


@router.get("/jobs", response_model=list[JobOut])
async def list_jobs(
    user: CurrentUser,
    session: DbSession,
    status_filter: JobStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[JobOut]:
    from sqlalchemy import select
    stmt = select(JobRecord).order_by(JobRecord.id.desc())
    if status_filter:
        stmt = stmt.where(JobRecord.status == status_filter.value)
    jobs = (await session.scalars(stmt.limit(limit).offset(offset))).all()
    return [JobOut.model_validate(j) for j in jobs]


@router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job(job_id: int, user: CurrentUser, session: DbSession) -> JobOut:
    job = await session.get(JobRecord, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return JobOut.model_validate(job)


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
async def cancel_job(job_id: int, user: CurrentUser, session: DbSession) -> JobOut:
    """Cancel a queued job. A running job is flagged for cooperative cancel."""
    job = await session.get(JobRecord, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    if job.status == JobStatus.QUEUED:
        job.status = JobStatus.CANCELLED
        job.finished_at = utcnow()
    elif job.status == JobStatus.RUNNING:
        job.params = {**job.params, "cancel_requested": True}
    else:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Job already finished ({job.status})")
    await record(session, AuditAction.JOB_CANCELLED, user_id=user.id,
                 username=user.username, details=f"job #{job.id}")
    await notify_event(session, "job_updated", job_id=job.id, status=job.status)
    return JobOut.model_validate(job)


# -- schedules ---------------------------------------------------------------

@router.get("/schedules", response_model=list[ScheduleOut])
async def list_schedules(admin: AdminUser, session: DbSession) -> list[ScheduleOut]:
    from sqlalchemy import select
    schedules = (await session.scalars(select(ScheduleRecord))).all()
    return [ScheduleOut.model_validate(s) for s in schedules]


@router.post("/schedules", response_model=ScheduleOut, status_code=201)
async def create_schedule(body: ScheduleCreate, admin: AdminUser, session: DbSession) -> ScheduleOut:
    try:
        from apscheduler.triggers.cron import CronTrigger
        CronTrigger.from_crontab(body.cron)
    except Exception as exc:
        raise HTTPException(400, f"Invalid cron expression: {exc}") from exc
    schedule = ScheduleRecord(
        job_type=body.job_type, params=body.params, cron=body.cron, enabled=body.enabled
    )
    session.add(schedule)
    await session.flush()
    return ScheduleOut.model_validate(schedule)


@router.delete("/schedules/{schedule_id}", status_code=204)
async def delete_schedule(schedule_id: int, admin: AdminUser, session: DbSession) -> None:
    schedule = await session.get(ScheduleRecord, schedule_id)
    if schedule is None:
        raise HTTPException(404, "Schedule not found")
    await session.delete(schedule)
