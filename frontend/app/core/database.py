"""API-backed "session" facade: replaces the template's local SQLite layer.

The NiceGUI frontend is a pure REST client of the backend — it never touches
the database directly. To keep the template's views untouched, ``get_session()``
yields an :class:`ApiSession` (an httpx-backed client bound to the current
user's JWTs) that the services consume with their original signatures:

    with get_session() as session:
        UserService(session).get_all_users()
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Iterator

from nicegui import app

from shared.client import SyncClient

logger = logging.getLogger(__name__)

# Backend base URL, from the environment (see docker-compose.yaml)
BACKEND_URL = os.environ.get('BACKEND_URL', 'http://localhost:8000')


class ApiSession:
    """Thin wrapper around a SyncClient so services see a stable object."""

    def __init__(self, client: SyncClient) -> None:
        self.client = client

    # -- generic passthrough used by the services --------------------------
    def get(self, path: str, **kwargs):
        return self.client.get(path, **kwargs)

    def post(self, path: str, **kwargs):
        return self.client.post(path, **kwargs)

    def put(self, path: str, **kwargs):
        return self.client.put(path, **kwargs)

    def patch(self, path: str, **kwargs):
        return self.client.patch(path, **kwargs)

    def delete(self, path: str, **kwargs):
        return self.client.delete(path, **kwargs)


def _tokens_from_storage() -> tuple[str | None, str | None]:
    storage = app.storage.user
    return storage.get('access_token'), storage.get('refresh_token')


def make_client() -> SyncClient:
    """Build a SyncClient carrying the current user's JWT (auto-refreshing)."""
    client = SyncClient(BACKEND_URL)
    access, refresh = _tokens_from_storage()
    if access and refresh:
        client.set_tokens(access, refresh)
    return client


def sync_tokens_to_storage(client: SyncClient) -> None:
    """Persist refreshed JWTs back into the browser session storage."""
    storage = app.storage.user
    storage['access_token'] = client._access_token
    storage['refresh_token'] = client._refresh_token


@contextmanager
def get_session() -> Iterator[ApiSession]:
    """Yield an API session, persisting refreshed tokens on exit."""
    client = make_client()
    try:
        yield ApiSession(client)
    finally:
        sync_tokens_to_storage(client)
        client.close()


def init_db() -> None:
    """Compatibility shim for the template's startup call.

    No local database anymore — just verify the backend is reachable and log
    the target. Fails soft: the login page shows the error if the API is down.
    """
    import httpx
    try:
        response = httpx.get(f'{BACKEND_URL}/health', timeout=5.0)
        if response.status_code == 200:
            logger.info('Backend API reachable at %s', BACKEND_URL)
        else:
            logger.warning('Backend API at %s answered HTTP %s', BACKEND_URL, response.status_code)
    except Exception as exc:  # noqa: BLE001 — the UI must still start
        logger.error('Backend API unreachable at %s: %s', BACKEND_URL, exc)
