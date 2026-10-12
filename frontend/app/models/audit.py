"""Audit log domain model.

The AuditAction enum lives in shared.enums (single source of truth shared with
the backend); it is re-exported here for the historical
``from models.audit import AuditAction`` imports. Only the AuditEntry
dataclass — a frontend-side view of one audit row — is defined here.
"""

from __future__ import annotations

from dataclasses import dataclass

from shared.enums import AuditAction

__all__ = ['AuditAction', 'AuditEntry']


@dataclass(frozen=True)
class AuditEntry:
    id: int
    created_at: str
    action: str
    username: str
    user_id: int | None = None
    target: str | None = None
    details: str | None = None
    ip: str | None = None
