"""Worker process: consumes the job queue and executes actions asynchronously.

Scalability: run N copies of this process (``python -m app.worker``) — each one
claims jobs with ``SELECT ... FOR UPDATE SKIP LOCKED`` so a job is executed
exactly once, fleet-wide.

This process also hosts the CRON scheduler that re-enqueues jobs from the
`schedules` table.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from sqlalchemy import select, text

from app.core.config import get_settings
from app.events import notify_event
from app.core.db import JobRecord, ScheduleRecord, get_session_factory, utcnow
from shared.enums import JobStatus

logger = logging.getLogger(__name__)

# --- job registry -------------------------------------------------------------
# Register real actions here. Each handler receives (job, params) and returns
# a JSON-serializable dict stored in jobs.result.

JobHandler = Callable[[JobRecord, dict[str, Any]], Awaitable[dict[str, Any]]]

_REGISTRY: dict[str, JobHandler] = {}


def register(job_type: str) -> Callable[[JobHandler], JobHandler]:
    def decorator(fn: JobHandler) -> JobHandler:
        _REGISTRY[job_type] = fn
        return fn
    return decorator


@register("demo.sleep")
async def demo_sleep(job: JobRecord, params: dict[str, Any]) -> dict[str, Any]:
    """Demo action: sleeps for params['seconds'] (default 5), checks cancel."""
    seconds = float(params.get("seconds", 5))
    slept = 0.0
    while slept < seconds:
        if params.get("cancel_requested"):
            raise CancelledError()
        await asyncio.sleep(min(1.0, seconds - slept))
        slept += 1.0
    return {"slept": slept}


class CancelledError(Exception):
    pass


# --- queue consumption --------------------------------------------------------

async def claim_next_jobs(batch_size: int) -> list[JobRecord]:
    """Atomically claim queued jobs, ordered by priority then age."""
    async with get_session_factory()() as session:
        result = await session.execute(
            select(JobRecord)
            .where(JobRecord.status == JobStatus.QUEUED.value)
            .order_by(JobRecord.priority, JobRecord.id)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        jobs = list(result.scalars().all())
        now = utcnow()
        for job in jobs:
            job.status = JobStatus.RUNNING
            job.started_at = now
            await notify_event(session, "job_updated", job_id=job.id, status=job.status)
        await session.commit()
        for job in jobs:
            await session.refresh(job)
        return jobs


async def execute_job(job_id: int) -> None:
    """Run one claimed job to a terminal status."""
    handler = _REGISTRY.get("")  # resolved below after reload
    async with get_session_factory()() as session:
        job = await session.get(JobRecord, job_id)
        if job is None:
            return
        params = dict(job.params or {})
        handler = _REGISTRY.get(job.job_type)
        try:
            if handler is None:
                raise RuntimeError(f"No handler registered for job_type '{job.job_type}'")
            # cooperative cancel for queued jobs flagged between claim and run
            if params.get("cancel_requested"):
                raise CancelledError()
            result = await handler(job, params)
            job.status = JobStatus.SUCCEEDED
            await notify_event(session, "job_updated", job_id=job.id, status=job.status)
            job.result = result
        except CancelledError:
            job.status = JobStatus.CANCELLED
            await notify_event(session, "job_updated", job_id=job.id, status=job.status)
        except Exception as exc:  # noqa: BLE001 — worker must survive any job failure
            logger.exception("Job %s failed", job_id)
            job.status = JobStatus.FAILED
            await notify_event(session, "job_updated", job_id=job.id, status=job.status)
            job.error = f"{type(exc).__name__}: {exc}"[:2000]
        job.finished_at = utcnow()
        await session.commit()


async def worker_loop(worker_id: str) -> None:
    """Main loop of one worker: claim and execute forever."""
    settings = get_settings()
    logger.info("Worker %s started (handlers: %s)", worker_id, ", ".join(_REGISTRY) or "none")
    while True:
        try:
            jobs = await claim_next_jobs(settings.worker_batch_size)
        except Exception:
            logger.exception("Claim failed")
            await asyncio.sleep(settings.worker_poll_interval * 5)
            continue
        if not jobs:
            await asyncio.sleep(settings.worker_poll_interval)
            continue
        # execute claimed jobs concurrently within this worker
        await asyncio.gather(*(execute_job(j.id) for j in jobs))


# --- CRON scheduler -----------------------------------------------------------

async def scheduler_tick() -> None:
    """One scheduler pass: enqueue jobs for enabled, due schedules.

    Kept deliberately simple for the skeleton: a schedule is 'due' when
    `croniter`-style next-fire computation is replaced by a coarse check.
    For production use APScheduler's CronTrigger per schedule.
    """
    import croniter
    async with get_session_factory()() as session:
        schedules = (await session.scalars(
            select(ScheduleRecord).where(ScheduleRecord.enabled.is_(True))
        )).all()
        for schedule in schedules:
            now = utcnow()
            base = schedule.last_run_at or (now - timedelta(days=1))
            iterator = croniter(schedule.cron, base)
            next_fire = iterator.get_next(croniter.datetime)
            if schedule.last_run_at is None or next_fire <= now:
                session.add(JobRecord(
                    job_type=schedule.job_type,
                    params=schedule.params,
                    created_by=f"schedule#{schedule.id}",
                    status=JobStatus.QUEUED,
                ))
                schedule.last_run_at = now
        await session.commit()


async def scheduler_loop(interval: float = 30.0) -> None:
    logger.info("Scheduler started")
    while True:
        try:
            await scheduler_tick()
        except Exception:
            logger.exception("Scheduler tick failed")
        await asyncio.sleep(interval)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    # Create the schema before claiming jobs: the worker may start before (or
    # without) the API container. ensure_schema() is idempotent.
    from app.bootstrap import ensure_schema
    await ensure_schema()

    worker_id = f"worker-{id(object()) & 0xffff:04x}"
    # One process = one worker loop + one scheduler pass driver.
    # In production, run the scheduler as a single dedicated instance
    # (e.g. SCHEDULER=1 env var on exactly one replica).
    import os
    tasks = [asyncio.create_task(worker_loop(worker_id))]
    if os.environ.get("SCHEDULER", "1") == "1":
        tasks.append(asyncio.create_task(scheduler_loop()))
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
