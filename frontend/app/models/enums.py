"""Domain enumerations shared across models, services and views.

Mirrors shared.enums on the wire — the backend seeds roles
`admin`, `operator` and `user`.
"""

from __future__ import annotations

import enum


class UserRole(enum.Enum):
    """Role-based access control levels."""

    ADMIN = 'admin'
    OPERATOR = 'operator'
    USER = 'user'

    @classmethod
    def values(cls) -> tuple[str, ...]:
        return tuple(member.value for member in cls)
