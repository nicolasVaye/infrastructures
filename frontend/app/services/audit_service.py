"""Audit service — same contract as the template, backed by the REST API.

Business and audit actions are now recorded by the backend itself (each API
endpoint writes its own audit trail), so the module-level :func:`record`
is a no-op that keeps the template's view code unchanged.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from shared.client.async_client import ApiError

from models.audit import AuditEntry

logger = logging.getLogger(__name__)


def _parse_ts(value) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or '')


class AuditService:
    def __init__(self, session) -> None:
        self.session = session  # core.database.ApiSession

    def log(self, *args, **kwargs) -> None:
        """Deprecated: the backend records audit entries server-side."""
        logger.debug('AuditService.log() is a no-op: auditing moved to the backend.')

    def get_recent(self, *, limit: int = 100, offset: int = 0,
                   action: str | None = None,
                   actions: list[str] | None = None) -> list[AuditEntry]:
        params: dict = {'limit': limit, 'offset': offset}
        if actions:
            # Multi-select filter: comma-separated values (see GET /audit).
            params['actions'] = ','.join(actions)
        elif action:
            params['action'] = action
        entries = self.session.get('/audit', params=params)
        return [
            AuditEntry(
                id=e['id'],
                created_at=_parse_ts(e.get('created_at')),
                action=e['action'],
                username=e['username'],
                user_id=e.get('user_id'),
                target=e.get('target'),
                details=e.get('details'),
                ip=e.get('ip'),
            )
            for e in entries
        ]

    def count(self, action: str | None = None,
              actions: list[str] | None = None) -> int:
        params: dict = {}
        if actions:
            # Same filter shape as get_recent, so the pager's total always
            # matches the rows it pages through.
            params['actions'] = ','.join(actions)
        elif action:
            params['action'] = action
        data = self.session.get('/audit/count', params=params or None)
        return int((data or {}).get('count', 0))

    def clear(self) -> int:
        count = self.count()
        self.session.delete('/audit')
        return count


def record(action, *, username: str = 'unknown', user_id: int | None = None,
           target: str | None = None, details: str | None = None,
           ip: str | None = None) -> None:
    """Compatibility shim: audit entries are recorded by the backend.

    Every mutating endpoint on the API writes its own audit trail, including
    the acting user and IP; nothing to do here.
    """
    logger.debug('audit_service.record(%s) is a no-op: auditing moved to the backend.', action)
