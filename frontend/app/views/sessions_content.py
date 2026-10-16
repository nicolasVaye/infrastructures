"""Connected sessions page (admin): who is connected, grouped by user, and kick.

Data comes from GET /sessions on the backend — web browsers, OIDC logins and
external automation clients all appear here, with their last heartbeat. A
per-user summary row lets the admin see at a glance how many sessions each
user holds and filter the table on a specific user. Each row also carries a
per-session activity sparkline (GET /activity/sessions): unlike the Users
tab's cumulative per-user graph, this one splits the activity per
browser/client — a user on Chrome and Firefox gets two distinct graphs.
"""

from __future__ import annotations

import re
from collections import Counter

from nicegui import app, ui

from components.dialogs import confirm_dialog, info_dialog
from components.notifications import notify
from components.pager import pager
from core.database import get_session
from services.i18n import bind_format, t
from services.tz import format_local, get_app_timezone
from views._common import activity_sparkline, safe_auto_refresh

# Rows rendered per page: all sessions stay fetched client-side (online
# badges, sparklines); only the RENDERED slice is paginated.
_PAGE_SIZE = 50

_client_icons = {
    'web': 'web',
    'automation': 'smart_toy',
    'pytest': 'science',
    'oidc': 'key',
}


def _ua_summary(ua: str | None) -> str | None:
    """Compact 'Browser · OS' label parsed from a raw User-Agent string."""
    if not ua:
        return None
    match = re.search(r'(Edg|OPR|Firefox|Chrome|Safari)/[\d.]+', ua)
    browser = None
    if match:
        name = match.group(1)
        browser = {'Edg': 'Edge', 'OPR': 'Opera', 'Safari': 'Safari',
                   'Chrome': 'Chrome', 'Firefox': 'Firefox'}.get(name)
    if 'Windows NT' in ua:
        os_name = 'Windows'
    elif 'Mac OS X' in ua:
        os_name = 'macOS'
    elif 'Android' in ua:
        os_name = 'Android'
    elif 'iPhone' in ua or 'iPad' in ua:
        os_name = 'iOS'
    elif 'Linux' in ua:
        os_name = 'Linux'
    else:
        os_name = None
    parts = [p for p in (browser, os_name) if p]
    if parts:
        return ' · '.join(parts)
    return ua[:40] + '…' if len(ua) > 40 else ua


def content() -> None:
    """Sessions tab of the /settings admin hub (no page header here:
    the hub renders one; the admin guard also lives in the hub)."""
    from shared.client.async_client import ApiError

    selected_user = {'username': None}

    # Live-update granularity: every table row is a set of PER-CELL
    # refreshables (user/avatar cell, client, ip, activity, last activity),
    # each with its own signature. `last_activity` moves with every
    # heartbeat (15s) and the activity bars with every navigation — with a
    # per-ROW refresh those updates rebuilt the avatar <img> of the whole
    # row, making all avatars blink; per-cell they only repaint the one
    # small value that changed.
    # 'search' filters rows client-side (data is already fetched); the
    # per-user chips only render when there are few enough of them — with
    # 150 connected users a chip row is unusable, the search input scales.
    # 'show_inactive' adds the zombie sessions (active=False): browsers
    # closed without logout, waiting for the nightly cleanup job.
    state: dict = {'data': {}, 'counts': Counter(), 'order': [],
                   'rows': {}, 'chips_sig': None,
                   'search': '', 'show_inactive': False, 'page': 1}

    def _fetch() -> bool:
        """Refresh state['data'] / state['counts'] from the backend.

        False on a 401 (session revoked — e.g. self-kick): the heartbeat
        redirects; the previously rendered rows simply stay in place.
        """
        try:
            with get_session() as api:
                query = '/sessions?include_inactive=true' if state['show_inactive'] \
                        else '/sessions'
                all_sessions = api.get(query)
                activity = {a['session_id']: a
                            for a in api.get('/activity/sessions') or []}
        except ApiError as exc:
            # 401: session revoked — the heartbeat redirects; previously
            # rendered rows simply stay in place. 403: the browser's
            # identity changed mid-session (same-browser login as a lesser
            # user — see the /settings role watcher): stop silently too,
            # the page is about to be closed.
            if getattr(exc, 'status_code', None) in (401, 403):
                return False
            raise
        state['counts'] = Counter(s['username'] for s in all_sessions)
        state['data'] = {
            s['id']: {**s, 'act': activity.get(s['id'])}
            for s in all_sessions
        }
        return True

    def _stable_ids() -> list[str]:
        """Session ids in a STABLE order (created_at, then id).

        The backend returns them by last_activity DESC, which every heartbeat
        (15s) reshuffles: using the response order as the render order made
        the whole table rebuild on every poll and blink all avatars. The
        chronological order is stable across polls — the table rebuilds
        only when a session actually appears or disappears.
        """
        return sorted(state['data'],
                      key=lambda sid: (state['data'][sid].get('created_at') or '',
                                      sid))

    # -- per-cell signatures ---------------------------------------------------
    def _sig_user(sid: str) -> tuple:
        d = state['data'][sid]
        return (d.get('username'), d.get('has_avatar'), d.get('avatar_version'),
                d.get('auth_provider'),
                d.get('idp_name'), state['counts'].get(d.get('username'), 0),
                bool(d.get('active', True)))

    def _sig_client(sid: str) -> tuple:
        d = state['data'][sid]
        return (d.get('client'), d.get('user_agent'))

    def _sig_ip(sid: str) -> tuple:
        return (state['data'][sid].get('ip'),)

    def _sig_activity(sid: str, display_tz) -> tuple:
        act = state['data'][sid].get('act') or {}
        return (tuple(act.get('bars') or []), act.get('last15', 0),
                act.get('last_activity'), str(display_tz))

    def _sig_last_activity(sid: str, display_tz) -> tuple:
        return (state['data'][sid].get('last_activity'), str(display_tz))

    # -- cell renderers (read state['data'] at RENDER time) --------------------
    def _render_user_cell(sid: str) -> None:
        s = state['data'][sid]
        inactive = not bool(s.get('active', True))
        if s.get('has_avatar'):
            # Profile photo of the session's user, loaded on demand from the
            # dedicated avatar route. Zombie sessions (no heartbeat, awaiting
            # cleanup) render dimmed so "connected" and "leftover" never
            # look the same.
            img = ui.image(
                f"/users/{s.get('user_id')}/avatar?v={s.get('avatar_version', 0)}"
            ).style(
                'width: 28px; height: 28px; border-radius: 50%; '
                'object-fit: cover; flex-shrink: 0;'
            )
            if inactive:
                img.style('filter: grayscale(1); opacity: 0.5;')
        else:
            icon = ui.icon('person', size='1rem').classes('text-muted')
            if inactive:
                icon.style('opacity: 0.5;')
        with ui.column().classes('flex-1 gap-0'):
            with ui.row().classes('items-center gap-2'):
                ui.label(s['username']).classes('truncate')
                if s['username'] == app.storage.user.get('username'):
                    with ui.element('span').classes('badge badge-default').style('gap: 4px;'):
                        ui.icon('verified_user', size='0.9rem')
                        ui.label(t('sessions.you'))
                # Local vs federated (IdP) source — same badge style
                # as the Users tab.
                if s.get('auth_provider') == 'idp' and s.get('idp_name'):
                    with ui.element('span').classes('badge badge-info').style('gap: 4px;'):
                        ui.icon('vpn_key', size='0.9rem')
                        ui.label(s['idp_name'])
                else:
                    with ui.element('span').classes('badge badge-default').style('gap: 4px;'):
                        ui.icon('person', size='0.9rem')
                        ui.label(t('users.source.local'))
                if inactive:
                    # Stale: silent for longer than the heartbeat TTL —
                    # the browser left without logout, the cleanup job
                    # will sweep the row.
                    with ui.element('span').classes('badge badge-default').style('gap: 4px;'):
                        ui.icon('cloud_off', size='0.9rem')
                        ui.label(t('users.offline'))
            if state['counts'][s['username']] > 1:
                # Informational: how many OTHER active sessions the
                # same user holds (other browsers, a second login,
                # automation clients...).
                bind_format(
                    ui.label().classes('text-xs text-muted'),
                    'sessions.other_sessions',
                    n=state['counts'][s['username']] - 1,
                )

    def _render_client_cell(sid: str) -> None:
        s = state['data'][sid]
        icon = _client_icons.get(s.get('client'), 'devices')
        with ui.element('span').classes('badge badge-default').style('gap: 4px;'):
            ui.icon(icon, size='0.9rem')
            ui.label(s.get('client') or 'unknown')
        # User-agent summary (e.g. "Chrome - Windows") under
        # the client badge; the tooltip carries the full UA.
        ua = s.get('user_agent')
        ua_label = _ua_summary(ua)
        if ua_label:
            with ui.element('div').classes('text-xs text-muted truncate').style(
                'max-width: 120px; margin-top: 2px;'
            ) as ua_el:
                ui.label(ua_label)
                if ua and ua != ua_label:
                    ua_el.tooltip(ua)

    def _render_activity_cell(sid: str) -> None:
        # Per-session sparkline: THIS browser/client only — the Users tab
        # shows the same activity merged per user.
        activity_sparkline(state['data'][sid].get('act'), get_app_timezone())

    def _make_row(sid: str) -> dict:
        """Build one table row as per-cell refreshables + signatures."""
        display_tz = get_app_timezone()
        cells: dict[str, object] = {}
        sigs = {
            'user': _sig_user(sid),
            'client': _sig_client(sid),
            'ip': _sig_ip(sid),
            'activity': _sig_activity(sid, display_tz),
            'last_activity': _sig_last_activity(sid, display_tz),
        }

        def _cell(name: str, wrapper, render) -> None:
            @ui.refreshable
            def cell() -> None:
                render()
            with wrapper():
                cell()
            cells[name] = cell

        with ui.row().classes('w-full items-center px-4 py-3 no-wrap').style(
            'border-bottom: 1px solid var(--border, #f4f4f5);'
        ):
            _cell('user',
                  lambda: ui.element('div').classes('flex-1 min-w-0'),
                  lambda: _render_user_cell(sid))
            _cell('client',
                  lambda: ui.element('div').style('width: 130px;'),
                  lambda: _render_client_cell(sid))
            _cell('ip',
                  lambda: ui.element('div').style('width: 130px;'),
                  lambda: ui.label(state['data'][sid].get('ip') or '—')
                          .classes('text-xs text-muted')
                          .style('font-family: monospace;'))
            _cell('activity',
                  lambda: ui.element('div').style('width: 150px;'),
                  lambda: _render_activity_cell(sid))
            _cell('last_activity',
                  lambda: ui.element('div').style('width: 190px;'),
                  lambda: ui.label(format_local(
                      state['data'][sid].get('last_activity'),
                      get_app_timezone())).classes('text-xs text-muted')
                      .style('font-family: monospace;'))

            # Kick button: static per row (the session id never changes);
            # its confirm dialog is row-scoped and needs no refresh.
            session_id = sid

            async def _kick(sid_: str = session_id) -> None:
                confirmed = await confirm_dialog(
                    t('sessions.kick_confirm').format(sid=sid_[:8]),
                    title=t('sessions.kick_title'), danger=True,
                )
                if not confirmed:
                    return
                try:
                    with get_session() as api:
                        api.delete(f'/sessions/{sid_}')
                except Exception as exc:  # noqa: BLE001
                    await info_dialog(str(exc), title=t('sessions.not_possible'), danger=True)
                    return
                notify(t('sessions.revoked'), type='warning')
                # The kicked session may be the caller's own: the reload
                # then runs unauthenticated and must not raise.
                safe_auto_refresh(_reload)()

            with ui.element('div').style('width: 90px;'):
                with ui.button(icon='logout', on_click=_kick) \
                        .props('flat dense color=negative'):
                    # Destructive action: red tooltip (design-system pattern).
                    ui.tooltip(t('sessions.revoke')).classes('tooltip tooltip-danger')
        return {'cells': cells, 'sigs': sigs}

    def _render_chips() -> None:
        """Per-user summary chips: how many connected sessions each user holds.

        Only rendered while the user count stays small (<= 8): with a large
        user base a wall of chips is unusable — the search input scales."""
        if len(state['counts']) > 8:
            return
        counts = state['counts']
        for username, count in sorted(counts.items()):
            active = selected_user['username'] == username
            with ui.element('button').classes(
                'badge badge-default cursor-pointer'
            ).style('gap: 6px;' + (' box-shadow: 0 0 0 2px #3b82f6;' if active else '')).on(
                'click', lambda _, u=username: _select_user(u)
            ):
                ui.icon('person', size='0.9rem')
                ui.label(f'{username} ({count})')

    def _select_user(username: str) -> None:
        if selected_user['username'] == username:
            selected_user['username'] = None
        else:
            selected_user['username'] = username
        state['page'] = 1
        _apply()

    def _apply() -> None:
        """Re-render the chips and ONLY the cells whose data actually changed."""
        display_tz = get_app_timezone()

        chips_sig = (tuple(sorted(state['counts'].items())), selected_user['username'],
                     len(state['counts']) <= 8)
        if chips_sig != state['chips_sig']:
            state['chips_sig'] = chips_sig
            chips.clear()
            with chips:
                _render_chips()

        sel = selected_user['username']
        search = state['search']
        filtered = [sid for sid in _stable_ids()
                    if (sel is None or state['data'][sid].get('username') == sel)
                    and (not search
                         or search in (state['data'][sid].get('username') or '').lower())]
        # Client-side pagination of the filtered list (clamped when the
        # filters or the live poll shrink the result set).
        total = len(filtered)
        pages = max(1, -(-total // _PAGE_SIZE))
        state['page'] = min(state['page'], pages)
        start = (state['page'] - 1) * _PAGE_SIZE
        order = filtered[start:start + _PAGE_SIZE]
        if order != list(state['rows'].keys()):
            # A session appeared/disappeared or the filter changed: rebuild
            # the rows container (rare — logins/logouts/kicks only).
            rows.clear()
            state['rows'].clear()
            with rows:
                if not order:
                    with ui.column().classes('card w-full items-center gap-2 p-8'):
                        ui.icon('cloud_off', size='2rem').classes('text-muted')
                        ui.label(t('sessions.empty')).classes('text-muted')
                for sid in order:
                    state['rows'][sid] = _make_row(sid)
            pager_view.refresh()
            return
        for sid in order:
            row = state['rows'][sid]
            new_sigs = {
                'user': _sig_user(sid),
                'client': _sig_client(sid),
                'ip': _sig_ip(sid),
                'activity': _sig_activity(sid, display_tz),
                'last_activity': _sig_last_activity(sid, display_tz),
            }
            for name, sig in new_sigs.items():
                if sig != row['sigs'].get(name):
                    row['sigs'][name] = sig
                    row['cells'][name].refresh()
        pager_view.refresh()

    def _goto_page(p: int) -> None:
        state['page'] = p
        _apply()

    def _reload() -> None:
        if _fetch():
            _apply()

    # Filter toolbar: username search (scales to any user count) + a switch
    # that ALSO fetches the zombie sessions (browser closed without logout,
    # waiting for the nightly cleanup job). Static: both only feed the
    # state consumed by _fetch/_apply.
    with ui.row().classes('w-full items-center gap-4 mb-2 no-wrap'):
        search_input = ui.input(placeholder=t('sessions.filter.search')) \
            .props('outlined dense clearable') \
            .style('max-width: 280px;')
        search_input.on_value_change(lambda e: (
            state.update(search=(e.value or '').strip().lower(), page=1),
            safe_auto_refresh(_apply)(),
        ))
        inactive_switch = ui.switch(t('sessions.filter.inactive')).props('dense')
        inactive_switch.on_value_change(lambda e: (
            state.update(show_inactive=bool(e.value), page=1),
            safe_auto_refresh(_reload)(),
        ))

    chips = ui.row().classes('w-full items-center gap-2 mb-2 flex-wrap')
    with ui.column().classes('card w-full gap-0 p-0'):
        with ui.row().classes('w-full items-center px-4 py-3 label-text').style(
            'border-bottom: 1px solid var(--border, #e4e4e7);'
        ):
            ui.label(t('sessions.col.user')).classes('flex-1')
            ui.label(t('sessions.col.client')).style('width: 130px;')
            ui.label(t('sessions.col.ip')).style('width: 130px;')
            ui.label(t('users.col.activity')).style('width: 150px;')
            ui.label(t('sessions.col.last_activity')).style('width: 190px;')
            ui.label(t('users.col.actions')).style('width: 90px;')
        rows = ui.column().classes('w-full gap-0')

    @ui.refreshable
    def pager_view() -> None:
        total = len(state['data'])
        if state['search'] or selected_user['username']:
            # The pager reports the FILTERED count, matching what is listed.
            sel = selected_user['username']
            search = state['search']
            total = sum(1 for sid in state['data']
                        if (sel is None or state['data'][sid].get('username') == sel)
                        and (not search or search in (
                            state['data'][sid].get('username') or '').lower()))
        pager(total, state['page'], _PAGE_SIZE, _goto_page)

    pager_view()
    _reload()

    # Live updates: logins/logouts/kicks push 'sessions_refresh_counter'
    # (this tab, another tab, another admin — even another backend replica);
    # avatar/name changes push 'users_refresh_counter' so the avatar cells
    # re-render immediately too. Both counters live in app.storage.user
    # (shared by every client/tab of the browser; the SSE drain timer lives
    # on the root page client, so client-scoped counters would never be
    # seen from here).
    seen = {'sessions': app.storage.user.get('sessions_refresh_counter', 0),
            'users': app.storage.user.get('users_refresh_counter', 0)}

    def _on_event() -> None:
        changed = False
        counter = app.storage.user.get('sessions_refresh_counter', 0)
        if counter != seen['sessions']:
            seen['sessions'] = counter
            changed = True
        counter = app.storage.user.get('users_refresh_counter', 0)
        if counter != seen['users']:
            seen['users'] = counter
            changed = True
        if changed:
            safe_auto_refresh(_reload)()

    ui.timer(1.0, _on_event)
    ui.timer(15.0, safe_auto_refresh(_reload))
