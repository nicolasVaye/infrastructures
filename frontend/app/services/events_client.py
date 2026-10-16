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
import time

import httpx

logger = logging.getLogger(__name__)

RECONNECT_DELAY = 2.0

# SSE read timeout: the backend sends a keepalive comment every 15s, so a
# healthy stream always delivers bytes well within this window. A silently
# dead connection (proxy hiccup, backend restart, token expiry mid-stream…)
# then raises ReadTimeout instead of hanging forever — the loop reconnects
# and the tab keeps receiving live events.
_STREAM_TIMEOUT = httpx.Timeout(connect=10.0, read=45.0, write=10.0, pool=10.0)

# Watchdog: hard upper bound between two chunks. Keepalives arrive every
# 15s, so a silent gap > WATCHDOG seconds means the pipe is dead even if
# httpx's own read-timeout never fires (observed in production: the stream
# delivers the first frame and then nothing, without any exception). The
# watchdog forces a disconnect → reconnect → Last-Event-ID replay instead
# of waiting forever on a zombie connection.
WATCHDOG = 25.0


def handle_event(evt: dict) -> None:
    """Apply one event. Must run in page context (accesses app.storage)."""
    from nicegui import app, ui
    storage = app.storage.user
    etype = evt.get('type')

    if etype == '_resync':
        # The backend could not replay everything the tab missed (gap larger
        # than the server-side buffer, e.g. after a long sleep of the laptop
        # or a backend restart): bump every refresh counter so all live
        # views rebuild from a fresh fetch. Never trust a stale cache after
        # a disconnection longer than the replay window.
        for key in ('sessions_refresh_counter', 'jobs_refresh_counter',
                    'schedules_refresh_counter'):
            storage[key] = storage.get(key, 0) + 1

    elif etype == 'user_updated':
        # Any user's profile changed (avatar, display name...) — the Users
        # and Sessions tabs listen for this counter and re-fetch their data;
        # their per-cell diff then re-renders ONLY the affected avatar/name
        # cells instead of waiting for the next 15s poll.
        storage['users_refresh_counter'] = storage.get('users_refresh_counter', 0) + 1
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

    elif etype == 'app_settings_changed':
        # The admin uploaded or reset the application logo (possibly from
        # ANOTHER browser: app.storage.user is per-browser and cannot carry
        # this). Bump the shared version — every tab's header timer re-renders
        # the logo within ~2s (header.py) — and swap the favicon link hrefs
        # with the new version so the browser drops its cached icon.
        if evt.get('setting') == 'logo':
            version = int(evt.get('version') or 0)
            storage['logo_version'] = version
            ui.run_javascript(
                "document.querySelectorAll('link[rel=\"icon\"], "
                "link[rel=\"apple-touch-icon\"]').forEach(function (l) {"
                "  var base = (l.getAttribute('href') || '').split('?')[0];"
                f"  l.setAttribute('href', base + '?v={version}');"
                "});"
            )


async def _stream_loop(queue: asyncio.Queue, user_storage, state: dict) -> None:
    """One SSE connection per tab; pushes parsed events into ``queue``.

    ``user_storage`` is the page's ``app.storage.user`` object captured at
    install time: a background task has no request context and must not go
    through ``app.storage``, but reading the captured object is safe and
    always sees the fresh access token written by the heartbeat.

    ``state['last_seq']`` tracks the server's event sequence number; on every
    (re)connection it is sent as the standard ``Last-Event-ID`` header so the
    backend replays the events emitted during the disconnect — no more blind
    windows between the death of a stream and its reconnection.
    """
    backend = os.environ.get('BACKEND_URL', 'http://localhost:8000')
    while True:
        try:
            token = user_storage.get('access_token')
            if not token:
                state['connected'] = False
                state['last_error'] = 'no access token'
                await asyncio.sleep(RECONNECT_DELAY)
                continue
            headers = {'Authorization': f'Bearer {token}'}
            if state.get('last_seq'):
                headers['Last-Event-ID'] = str(state['last_seq'])
            async with httpx.AsyncClient(base_url=backend, timeout=_STREAM_TIMEOUT) as client:
                async with client.stream(
                    'GET', '/events',
                    headers=headers,
                ) as response:
                    if response.status_code != 200:
                        # Auth rejection (401) or backend error: report the
                        # actual status — a loop that fails invisibly looks
                        # exactly like "SSE does not work".
                        state['connected'] = False
                        state['last_error'] = f'HTTP {response.status_code} on /events'
                        logger.info('Event stream rejected: HTTP %s (retry in %.0fs)',
                                    response.status_code, RECONNECT_DELAY)
                        await asyncio.sleep(RECONNECT_DELAY)
                        continue
                    state['connected'] = True
                    state['last_error'] = None
                    state['connects'] = state.get('connects', 0) + 1
                    logger.info('Event stream connected (attempt #%s, last_seq=%s)',
                                state['connects'], state.get('last_seq', 0))
                    buffer = ''
                    aiter = response.aiter_bytes()
                    while True:
                        # Manual anext + wait_for: a guaranteed watchdog on
                        # top of httpx's read-timeout, which can silently
                        # never fire on a half-open connection.
                        try:
                            chunk = await asyncio.wait_for(
                                aiter.__anext__(), timeout=WATCHDOG)
                        except StopAsyncIteration:
                            # Server closed the stream cleanly: reconnect.
                            state['connected'] = False
                            state['last_error'] = 'stream closed by server'
                            logger.info('Event stream ended by server '
                                        '(last_seq=%s); reconnecting',
                                        state.get('last_seq', 0))
                            break
                        except asyncio.TimeoutError:
                            # No bytes within the watchdog window although
                            # the backend sends a keepalive every 15s: the
                            # pipe is dead. Drop the connection and replay
                            # from Last-Event-ID on the next one.
                            state['connected'] = False
                            state['last_error'] = (
                                f'watchdog fired: no data for {WATCHDOG:.0f}s')
                            logger.info(
                                'SSE watchdog fired (no chunk in %.0fs, '
                                'last_seq=%s); reconnecting',
                                WATCHDOG, state.get('last_seq', 0))
                            break
                        state['connected'] = True
                        # Any chunk (keepalives included) proves the stream
                        # is alive; the diagnostics panel uses this age.
                        state['last_chunk_ts'] = time.time()
                        buffer += chunk.decode('utf-8', errors='replace')
                        while '\n\n' in buffer:
                            frame, buffer = buffer.split('\n\n', 1)
                            for line in frame.splitlines():
                                if line.startswith('data: '):
                                    try:
                                        evt = json.loads(line[6:])
                                    except Exception:  # noqa: BLE001
                                        continue
                                    state['events'] = state.get('events', 0) + 1
                                    state['last_event_ts'] = time.time()
                                    queue.put_nowait(evt)
                                elif line.startswith('id: '):
                                    # Track the sequence so the NEXT
                                    # connection replays from here. A hole
                                    # (event dropped server-side on a slow
                                    # consumer) is self-healed: force a
                                    # resync of all live views.
                                    try:
                                        seq = int(line[4:])
                                        last = state.get('last_seq', 0)
                                        if last and seq > last + 1:
                                            queue.put_nowait({'type': '_resync'})
                                        state['last_seq'] = seq
                                    except ValueError:
                                        pass
        except asyncio.CancelledError:
            logger.info('Event stream task cancelled (last_seq=%s)',
                        state.get('last_seq', 0))
            raise
        except Exception as exc:  # noqa: BLE001 — always reconnect
            state['connected'] = False
            state['last_error'] = str(exc)
            logger.info('Event stream error (%s); reconnecting in %.0fs',
                        exc, RECONNECT_DELAY)
            await asyncio.sleep(RECONNECT_DELAY)


def install_event_listener() -> None:
    """Wire this tab's SSE listener + queue-draining timer (page context)."""
    import asyncio as _asyncio
    from nicegui import app, context, ui

    if app.storage.client.get('events_installed'):
        return
    app.storage.client['events_installed'] = True

    queue: _asyncio.Queue = _asyncio.Queue(maxsize=256)
    app.storage.client['events_queue'] = queue
    state = {'last_seq': 0}
    app.storage.client['events_state'] = state
    app.storage.client['events_task'] = _asyncio.create_task(
        _stream_loop(queue, app.storage.user, state))

    # Lifecycle hooks MUST be per-client: NiceGUI's app-level on_disconnect
    # fires for EVERY disconnecting client (any tab, any browser, any user),
    # so registering task.cancel() there let any unrelated disconnect kill
    # this tab's stream — the silent "connected but starved" SSE zombie
    # (cancelled task: no chunks, no watchdog, no read-timeout, no retry).
    # Both handlers act on the CURRENT task, never a captured one.
    client = context.client

    def _cancel_stream() -> None:
        task = app.storage.client.get('events_task')
        if task is not None:
            task.cancel()

    def _rearm_stream() -> None:
        # on_disconnect also fires on transient socket drops that reconnect
        # seconds later (NiceGUI grace period), and the page builder does NOT
        # re-run on reconnect: restart the stream task here so a websocket
        # hiccup never leaves the tab without live events.
        task = app.storage.client.get('events_task')
        if task is None or task.done():
            app.storage.client['events_task'] = _asyncio.create_task(
                _stream_loop(queue, app.storage.user, state))

    client.on_disconnect(_cancel_stream)
    client.on_connect(_rearm_stream)

    def _drain() -> None:
        # Mirror the SSE loop's health into the SHARED user storage so the
        # diagnostics panel (any tab) can show connect state / last event /
        # last error — the first place to look when live updates seem dead.
        app.storage.user['sse_status'] = {
            'connected': bool(state.get('connected')),
            'last_error': state.get('last_error'),
            'last_seq': state.get('last_seq', 0),
            'last_chunk_ts': state.get('last_chunk_ts'),
            'events': state.get('events', 0),
            'connects': state.get('connects', 0),
        }
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
