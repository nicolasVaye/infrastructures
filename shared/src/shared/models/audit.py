"""Audit trail DTOs."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    action: str
    username: str
    user_id: int | None = None
    target: str | None = None
    details: str | None = None
    ip: str | None = None
