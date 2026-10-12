"""Domain enumerations — re-exported from the shared package.

UserRole & co are defined ONCE in shared.enums so the backend, the frontend
and external clients always agree on the stable API values. This module only
re-exports them for the historical ``from models.enums import ...`` imports.
"""

from __future__ import annotations

from shared.enums import AuthProvider, JobStatus, SessionStatus, UserRole

__all__ = ['AuthProvider', 'JobStatus', 'SessionStatus', 'UserRole']
