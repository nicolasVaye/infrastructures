"""Job and schedule DTOs: actions submitted by clients, executed by workers."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from shared.enums import JobStatus


class JobCreate(BaseModel):
    """Request body of POST /jobs: submit an action for asynchronous execution."""

    job_type: str = Field(min_length=1, max_length=64, examples=["demo.sleep"])
    params: dict[str, Any] = Field(default_factory=dict)
    created_by: str | None = None  # optional label for external automations
    priority: int = Field(default=5, ge=0, le=9)


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_type: str
    params: dict[str, Any] = {}
    status: JobStatus
    priority: int
    result: dict[str, Any] | None = None
    error: str | None = None
    created_by: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class JobStatusOut(BaseModel):
    """Lightweight status payload used for polling."""

    id: int
    status: JobStatus
    error: str | None = None


class ScheduleCreate(BaseModel):
    """CRON-based schedule that periodically submits a job."""

    job_type: str
    params: dict[str, Any] = Field(default_factory=dict)
    cron: str = Field(examples=["*/5 * * * *"])
    enabled: bool = True


class ScheduleUpdate(BaseModel):
    """PATCH /schedules/{id}: partial update of a schedule."""

    params: dict[str, Any] | None = None
    cron: str | None = None
    enabled: bool | None = None


class ScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_type: str
    params: dict[str, Any] = {}
    cron: str
    enabled: bool
    last_run_at: datetime | None = None
