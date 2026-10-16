"""Worker smoke test: claim → execute → succeed, directly against SQLite."""

from __future__ import annotations

import pytest


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_worker_executes_job(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/w.db")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("INSECURE_DEV", "1")

    from app.core import config
    config.get_settings.cache_clear()
    import app.core.db as db
    db._engine = None
    db._session_factory = None

    # create schema + seed
    from app.bootstrap import ensure_schema as _seed
    from app.core.db import JobRecord, get_session_factory
    from shared.enums import JobStatus
    await _seed()

    async with get_session_factory()() as session:
        session.add(JobRecord(job_type="demo.sleep", params={"seconds": 0.1},
                              status=JobStatus.QUEUED))
        await session.commit()

    from app.worker import claim_next_jobs, execute_job
    jobs = await claim_next_jobs(5)
    assert len(jobs) == 1
    assert jobs[0].status == JobStatus.RUNNING

    await execute_job(jobs[0].id)

    async with get_session_factory()() as session:
        job = await session.get(JobRecord, jobs[0].id)
        assert job.status == JobStatus.SUCCEEDED
        assert job.result == {"slept": 0.1}
