"""Live change events: per-tab SSE subscription to the backend's /events.

The backend pushes change events through Postgres LISTEN/NOTIFY (see the
backend's app/events.py) and streams them over SSE. Every NiceGUI tab
subscribes here (started from the base layout) and reacts in pure Python:

- ``user_updated``     → refresh the profile snapshot + header (an avatar or
                         name change propagates instantly, across tabs AND
                         across browsers for the same user);
- ``session_revoked``  → if the revoked session is OURS, local logout and
                         redirect to /login (cross-browser kick/logout);
- ``job_updated``      → bump a counter; the /jobs page's own timer sees it
                         and refreshes the kanban board.

NiceGUI constraint handled here: a background task has no page context, so
it must not touch ``app.storage``. The SSE task therefore only pushes parsed
events into a per-client :class:`asyncio.Queue`; a short ``ui.timer`` in the
page (see :func:`install_event_listener`) drains the queue in page context
and applies the handlers. The stream auto-reconnects with a small backoff;
transient errors never log the user out (the heartbeat digest remains the
safety net for profile state).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

import httpx

logger = logging.getLogger(__name__)

RECONNECT_DELAY = 2.0


def handle_event(evt: dict) -> None:
    """Apply one event. Must run in page context (accesses app.storage)."""
    from nicegui import app, ui
    storage = app.storage.user
    etype = evt.get('type')

    if etype == 'user_updated':
        if evt.get('user_id') == storage.get('user_id'):
            changed = (
                bool(evt.get('has_avatar')) != bool(storage.get('has_avatar'))
                or int(evt.get('avatar_version') or 0) != int(storage.get('avatar_version') or 0)
                or (evt.get('display_name') or None) != storage.get('display_name')
            )
            if changed:
                storage['has_avatar'] = bool(evt.get('has_avatar'))
                storage['avatar_version'] = int(evt.get('avatar_version') or 0)
                storage['display_name'] = evt.get('display_name') or None
                refresh_header = app.storage.client.get('header_account_refresh')
                if refresh_header is not None:
                    refresh_header()

    elif etype == 'session_revoked':
        # The localStorage storage-event channel only covers tabs of the SAME
        # browser; this SSE event reaches every browser of the same user.
        sid = evt.get('session_id')
        if sid and sid == storage.get('session_id'):
            storage.clear()
            ui.run_javascript('window.location.href = "/login"')

    elif etype == 'job_updated':
        counter = storage.get('jobs_refresh_counter', 0)
        storage['jobs_refresh_counter'] = counter + 1

    elif etype == 'schedule_updated':
        # A schedule was created/edited/deleted (possibly by another admin):
        # let the /jobs page rebuild its schedules panel.
        counter = storage.get('schedules_refresh_counter', 0)
        storage['schedules_refresh_counter'] = counter + 1

    elif etype == 'sessions_changed':
        # A login/logout/kick (this tab, another tab, or another admin)
        # changed who is connected: let the Sessions tab refresh instantly.
        counter = storage.get('sessions_refresh_counter', 0)
        storage['sessions_refresh_counter'] = counter + 1


async def _stream_loop(queue: asyncio.Queue, user_storage) -> None:
    """One SSE connection per tab; pushes parsed events into ``queue``.

    ``user_storage`` is the page's ``app.storage.user`` object captured at
    install time: a background task has no request context and must not go
    through ``app.storage``, but reading the captured object is safe and
    always sees the fresh access token written by the heartbeat.
    """
    backend = os.environ.get('BACKEND_URL', 'http://localhost:8000')
    while True:
        try:
            token = user_storage.get('access_token')
            if not token:
                await asyncio.sleep(RECONNECT_DELAY)
                continue
            async with httpx.AsyncClient(base_url=backend, timeout=None) as client:
                async with client.stream(
                    'GET', '/events',
                    headers={'Authorization': f'Bearer {token}'},
                ) as response:
                    if response.status_code != 200:
                        await asyncio.sleep(RECONNECT_DELAY)
                        continue
                    buffer = ''
                    async for chunk in response.aiter_text():
                        buffer += chunk
                        while '\n\n' in buffer:
                            frame, buffer = buffer.split('\n\n', 1)
                            for line in frame.splitlines():
                                if line.startswith('data: '):
                                    try:
                                        evt = json.loads(line[6:])
                                    except Exception:  # noqa: BLE001
                                        continue
                                    queue.put_nowait(evt)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — always reconnect
            logger.debug('Event stream error: %s', exc)
            await asyncio.sleep(RECONNECT_DELAY)


def install_event_listener() -> None:
    """Wire this tab's SSE listener + queue-draining timer (page context)."""
    import asyncio as _asyncio
    from nicegui import app, ui

    if app.storage.client.get('events_installed'):
        return
    app.storage.client['events_installed'] = True

    queue: _asyncio.Queue = _asyncio.Queue(maxsize=256)
    app.storage.client['events_queue'] = queue
    task = _asyncio.create_task(_stream_loop(queue, app.storage.user))
    app.storage.client['events_task'] = task
    app.on_disconnect(lambda: task.cancel())

    def _drain() -> None:
        while not queue.empty():
            try:
                evt = queue.get_nowait()
            except _asyncio.QueueEmpty:  # pragma: no cover
                break
            try:
                handle_event(evt)
            except Exception as exc:  # noqa: BLE001 — one bad event stops nothing
                logger.debug('Event handler error: %s', exc)

    ui.timer(0.5, _drain)
