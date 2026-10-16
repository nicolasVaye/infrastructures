"""Session tracking DTOs: who is connected, from where, since when."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: int
    username: str
    client: str
    ip: str | None = None
    user_agent: str | None = None
    created_at: datetime
    last_activity: datetime
    revoked_at: datetime | None = None
    expires_at: datetime
    auth_provider: str = "local"
    idp_name: str | None = None
    avatar: str | None = None
    # False when the session is no longer "connected" (no heartbeat within
    # the TTL) but still lingering un-revoked in the DB until the cleanup
    # job sweeps it: the Sessions tab renders those as inactive.
    active: bool = True
