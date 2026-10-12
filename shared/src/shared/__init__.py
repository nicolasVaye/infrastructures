"""Shared package: single source of truth for DTOs, enums and API clients.

Installed by both `backend` and `frontend` (editable in dev:
`uv pip install -e ../shared`), so serialization/deserialization models are
never duplicated between the two projects.
"""

__version__ = "0.1.0"
