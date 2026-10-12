"""Typed API clients built on the shared DTOs.

Two flavours:
- :class:`AsyncClient`: httpx-based async client for external automations,
  scripts and services (shares nothing but the DTOs with the frontend).
- :class:`SyncClient`: synchronous facade used by the NiceGUI frontend.
"""

from shared.client.async_client import ApiError, AsyncClient
from shared.client.sync_client import SyncClient

__all__ = ["ApiError", "AsyncClient", "SyncClient"]
