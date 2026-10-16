"""Users administration page: manage users (tab 1) and roles (tab 2).

Admin-only. All persistence goes through :class:`services.user_service.UserService`;
this view only orchestrates the UI and delegates every mutation to the service.
The page is split into two tabs: Users (create/delete/toggle/reset) and Roles
(read-only catalog fetched from GET /roles, with user counts).
"""

from __future__ import annotations

from nicegui import app, ui

from components.dialogs import confirm_dialog, info_dialog
from components.notifications import notify
from core.database import get_session
from models.audit import AuditAction
from models.enums import UserRole
from services.audit_service import record as audit_record
from services.i18n import t
from services.user_service import UserService
from services.tz import get_app_timezone
from views._common import activity_sparkline, safe_auto_refresh


# The bootstrap admin is protected: it can never be deleted or disabled.
_PROTECTED_USERNAME = 'admin'

# Icons are classic Material Icons (Quasar's bundled set). All three roles
# seeded by the backend appear here (admin, operator, user).
_ROLE_BADGE = {
    UserRole.ADMIN.value:    ('badge badge-warning', 'admin_panel_settings', 'users.role.admin'),
    UserRole.OPERATOR.value: ('badge badge-info',    'engineering',          'users.role.operator'),
    UserRole.USER.value:     ('badge badge-default', 'person',               'users.role.user'),
}

_ROLE_DESC_KEY = {
    UserRole.ADMIN.value: 'roles.desc.admin',
    UserRole.OPERATOR.value: 'roles.desc.operator',
    UserRole.USER.value: 'roles.desc.user',
}


def _role_label(role: str) -> str:
    entry = _ROLE_BADGE.get(role)
    return t(entry[2]) if entry else role


def users_tab() -> None:
    """Users management panel (used as a tab inside /settings)."""
    _users_tab(app.storage.user.get('username', ''))


def roles_tab() -> None:
    """Roles catalog panel (used as a tab inside /settings)."""
    _roles_tab()


# ================================================================= users tab
def _users_tab(current_username: str) -> None:

    # Live-update granularity: every table row is a set of PER-CELL
    # refreshables (avatar/user cell, role, source, online, activity,
    # status, actions), each with its own signature. A refresh re-renders
    # only the cells whose data moved — volatile cells (activity bars of
    # the currently navigating user, online badges) no longer rebuild the
    # avatar <img> of every row, which made all avatars blink. The whole
    # row set is rebuilt only when a user is created or deleted.
    state: dict = {'data': {}, 'order': [], 'rows': {}}

    def _fetch() -> None:
        """Refresh state['data'] / state['order'] from the backend."""
        with get_session() as session:
            users = [
                {
                    'id': u.id,
                    'username': u.username,
                    'role': u.role.value,
                    'is_active': u.is_active,
                    'must_change_password': u.must_change_password,
                    'auth_provider': u.auth_provider,
                    'idp_name': u.idp_name,
                    'has_avatar': u.has_avatar,
                    'avatar_version': u.avatar_version,
                }
                for u in UserService(session).get_all_users()
            ]

        # Connected users: usernames holding at least one active session
        # (GET /sessions — this tab is admin-only, same guard as the API).
        # A fetch failure only degrades this cosmetic column to "unknown".
        try:
            with get_session() as session:
                online = {s['username'] for s in session.get('/sessions') or []}
        except Exception:  # noqa: BLE001 — column stays neutral on API error
            online = None

        # 4-hour activity sparklines (GET /activity/users), cumulative per
        # user across all their sessions/browsers. Same defensive pattern.
        try:
            with get_session() as session:
                activity = {a['username']: a
                            for a in session.get('/activity/users') or []}
        except Exception:  # noqa: BLE001
            activity = None

        state['order'] = [u['id'] for u in users]
        state['data'] = {
            u['id']: {
                **u,
                'online': online,
                'act': (activity or {}).get(u['username'])
                       if activity is not None else None,
            }
            for u in users
        }

    # -- per-cell signatures: a cell re-renders only when ITS data moved ----
    def _sig_user(uid: int) -> tuple:
        d = state['data'][uid]
        return (d['username'], d.get('has_avatar'), d.get('avatar_version'),
                d['must_change_password'], d['auth_provider'])

    def _sig_role(uid: int) -> tuple:
        return (state['data'][uid]['role'],)

    def _sig_source(uid: int) -> tuple:
        d = state['data'][uid]
        return (d['auth_provider'], d['idp_name'])

    def _sig_online(uid: int) -> tuple:
        d = state['data'][uid]
        online = d['online']
        return (None if online is None else d['username'] in online,)

    def _sig_activity(uid: int, display_tz) -> tuple:
        act = state['data'][uid]['act'] or {}
        return (tuple(act.get('bars') or []), act.get('last15', 0),
                act.get('last_activity'), str(display_tz))

    def _sig_status(uid: int) -> tuple:
        return (state['data'][uid]['is_active'],)

    def _sig_actions(uid: int) -> tuple:
        d = state['data'][uid]
        return (d['is_active'], d['auth_provider'],
                d['username'] == current_username,
                d['username'] == _PROTECTED_USERNAME)

    # -- cell renderers (read state['data'] at RENDER time) ------------------
    def _render_user_cell(uid: int) -> None:
        u = state['data'][uid]
        with ui.row().classes('flex-1 items-center gap-3 min-w-0'):
            if u.get('has_avatar'):
                # Profile photo, loaded on demand from the dedicated avatar
                # route (versioned URL = browser cache busts on change).
                ui.image(f"/users/{u['id']}/avatar?v={u.get('avatar_version', 0)}").style(
                    'width: 32px; height: 32px; border-radius: 50%; '
                    'object-fit: cover; flex-shrink: 0;'
                )
            else:
                with ui.element('div').classes(
                    'flex items-center justify-center rounded-full'
                ).style(
                    'width: 32px; height: 32px; background: #f4f4f5; '
                    'color: #18181b; font-weight: 600; flex-shrink: 0;'
                ):
                    ui.label(u['username'][:1].upper())
            with ui.column().classes('gap-0 min-w-0'):
                ui.label(u['username']).classes('truncate').style('font-weight: 500;')
                # Federated accounts have no local password: the
                # "password change pending" hint never applies.
                if u['must_change_password'] and u['auth_provider'] == 'local':
                    ui.label(t('users.pw_pending')).classes('text-xs text-muted')

    def _render_role_cell(uid: int) -> None:
        u = state['data'][uid]
        badge_cls, badge_icon, _label_key = _ROLE_BADGE.get(
            u['role'], _ROLE_BADGE[UserRole.USER.value])
        with ui.element('span').classes(badge_cls).style('gap: 4px;'):
            ui.icon(badge_icon, size='0.9rem')
            ui.label(_role_label(u['role']))

    def _render_source_cell(uid: int) -> None:
        u = state['data'][uid]
        # Local account vs federated through an IdP. The icon+badge make
        # them visually distinct even if a provider happens to be named
        # "Local".
        if u['auth_provider'] == 'local':
            with ui.element('span').classes('badge badge-default').style('gap: 4px;'):
                ui.icon('person', size='0.9rem')
                ui.label(t('users.source.local'))
        else:
            with ui.element('span').classes('badge badge-info').style('gap: 4px;'):
                ui.icon('vpn_key', size='0.9rem')
                ui.label(u['idp_name'] or t('users.source.idp'))

    def _render_online_cell(uid: int) -> None:
        u = state['data'][uid]
        online = u['online']
        if online is None:
            ui.label('—').classes('text-xs text-muted')
        elif u['username'] in online:
            with ui.element('span').classes('badge badge-success').style('gap: 4px;'):
                ui.icon('fiber_manual_record', size='0.6rem')
                ui.label(t('users.online'))
        else:
            with ui.element('span').classes('badge badge-default').style('gap: 4px;'):
                ui.icon('fiber_manual_record', size='0.6rem')
                ui.label(t('users.offline'))

    def _render_activity_cell(uid: int) -> None:
        activity_sparkline(state['data'][uid].get('act'), get_app_timezone())

    def _render_status_cell(uid: int) -> None:
        if state['data'][uid]['is_active']:
            with ui.element('span').classes('badge badge-success'):
                ui.label(t('status.active'))
        else:
            with ui.element('span').classes('badge badge-default'):
                ui.label(t('status.inactive'))

    def _render_actions_cell(uid: int) -> None:
        u = state['data'][uid]
        is_self = u['username'] == current_username
        is_protected = u['username'] == _PROTECTED_USERNAME
        with ui.row().classes('items-center gap-1'):
            reset_btn = ui.button(icon='lock_reset',
                                  on_click=lambda _, uid=u['id']: _reset(uid)) \
                .props('flat dense round').tooltip(t('users.tip.reset'))
            # Federated accounts have no local password: the reset
            # button makes no sense for them.
            if u['auth_provider'] != 'local':
                reset_btn.disable()
                reset_btn.tooltip(t('users.tip.reset_federated'))

            role_btn = ui.button(
                icon='swap_horiz', on_click=lambda _, uid=u['id']: _change_role(uid)
            ).props('flat dense round').tooltip(t('users.tip.switch_role'))

            active_icon = 'block' if u['is_active'] else 'check_circle'
            active_btn = ui.button(
                icon=active_icon, on_click=lambda _, uid=u['id']: _toggle_active(uid)
            ).props('flat dense round').tooltip(
                t('users.tip.deactivate') if u['is_active'] else t('users.tip.activate')
            )

            delete_btn = ui.button(
                icon='delete',
                on_click=lambda _, uid=u['id'], name=u['username']: _delete(uid, name),
            ).props('flat dense round color=negative').tooltip(t('users.tip.delete'))

            if is_protected or is_self:
                active_btn.disable()
                delete_btn.disable()
            if is_protected:
                role_btn.disable()

    def _make_row(uid: int) -> dict:
        """Build one table row as per-cell refreshables + signatures."""
        display_tz = get_app_timezone()
        cells: dict[str, object] = {}
        sigs = {
            'user': _sig_user(uid),
            'role': _sig_role(uid),
            'source': _sig_source(uid),
            'online': _sig_online(uid),
            'activity': _sig_activity(uid, display_tz),
            'status': _sig_status(uid),
            'actions': _sig_actions(uid),
        }

        def _cell(name: str, wrapper, render) -> None:
            @ui.refreshable
            def cell() -> None:
                render()
            with wrapper():
                cell()
            cells[name] = cell

        with ui.row().classes('w-full items-center px-4 py-3').style(
            'border-bottom: 1px solid var(--border, #f4f4f5);'
        ):
            _cell('user',
                  lambda: ui.element('div').classes('flex-1 min-w-0'),
                  lambda: _render_user_cell(uid))
            _cell('role',
                  lambda: ui.element('div').style('width: 120px;'),
                  lambda: _render_role_cell(uid))
            _cell('source',
                  lambda: ui.element('div').style('width: 140px;'),
                  lambda: _render_source_cell(uid))
            _cell('online',
                  lambda: ui.element('div').style('width: 110px;'),
                  lambda: _render_online_cell(uid))
            _cell('activity',
                  lambda: ui.element('div').style('width: 150px;'),
                  lambda: _render_activity_cell(uid))
            _cell('status',
                  lambda: ui.element('div').style('width: 120px;'),
                  lambda: _render_status_cell(uid))
            _cell('actions',
                  lambda: ui.row().classes('items-center gap-1').style('width: 180px;'),
                  lambda: _render_actions_cell(uid))
        return {'cells': cells, 'sigs': sigs}

    def _apply() -> None:
        """Re-render ONLY the cells whose data actually changed."""
        display_tz = get_app_timezone()
        if state['order'] != list(state['rows'].keys()):
            # A user was created or deleted: rebuild the rows container.
            rows.clear()
            state['rows'].clear()
            with rows:
                for uid in state['order']:
                    state['rows'][uid] = _make_row(uid)
            return
        for uid in state['order']:
            row = state['rows'][uid]
            new_sigs = {
                'user': _sig_user(uid),
                'role': _sig_role(uid),
                'source': _sig_source(uid),
                'online': _sig_online(uid),
                'activity': _sig_activity(uid, display_tz),
                'status': _sig_status(uid),
                'actions': _sig_actions(uid),
            }
            for name, sig in new_sigs.items():
                if sig != row['sigs'].get(name):
                    row['sigs'][name] = sig
                    row['cells'][name].refresh()

    def _reload() -> None:
        _fetch()
        _apply()

    # Action handlers
    async def _reset(uid: int) -> None:
        try:
            with get_session() as session:
                service = UserService(session)
                target = service.get_user(uid)
                new_password = service.reset_password(uid)
        except ValueError as exc:
            await info_dialog(str(exc), title=t('users.not_possible'), danger=True)
            return
        audit_record(AuditAction.PASSWORD_RESET, target=target.username if target else str(uid))
        # The backend generates a RANDOM password per reset (never a shared
        # constant): show the one-time value to the admin.
        notify(t('users.pw_reset').format(pw=new_password or '—'), type='positive')
        _reload()

    def _change_role(uid: int) -> None:
        """Open a dialog to pick any of the three roles (admin/operator/user)."""
        with get_session() as session:
            user = UserService(session).get_user(uid)
        if user is None:
            return

        with ui.dialog() as dialog, ui.column().classes('login-card gap-4'):
            ui.label(t('users.change_role_title').format(name=user.username)).classes('section-title')
            ui.label(t('users.change_role_hint')).classes('text-xs text-muted')

            ui.label(t('users.col.role')).classes('field-label')
            new_role = ui.select(
                options={
                    UserRole.USER.value: _role_label(UserRole.USER.value),
                    UserRole.OPERATOR.value: _role_label(UserRole.OPERATOR.value),
                    UserRole.ADMIN.value: _role_label(UserRole.ADMIN.value),
                },
                value=user.role.value,
            ).props('outlined dense').classes('w-full')

            async def save() -> None:
                role = UserRole(new_role.value)
                if role is user.role:
                    dialog.close()
                    return
                try:
                    with get_session() as session:
                        UserService(session).set_role(uid, role)
                except ValueError as exc:
                    await info_dialog(str(exc), title=t('users.not_possible'), danger=True)
                    return
                audit_record(AuditAction.ROLE_CHANGED, target=user.username, details=role.value)
                notify(t('users.role_changed').format(name=user.username, role=_role_label(role.value)),
                       type='positive')
                dialog.close()
                _reload()

            with ui.row().classes('w-full justify-end gap-2'):
                ui.button(t('common.cancel'), on_click=dialog.close).classes('button button-secondary')
                ui.button(t('common.save'), on_click=save).classes('button button-primary')

        dialog.open()

    async def _toggle_active(uid: int) -> None:
        try:
            with get_session() as session:
                service = UserService(session)
                user = service.get_user(uid)
                if user is None:
                    return
                service.set_active(uid, not user.is_active)
        except ValueError as exc:
            await info_dialog(str(exc), title=t('users.not_possible'), danger=True)
            return
        activated = not user.is_active
        audit_record(
            AuditAction.USER_ACTIVATED if activated else AuditAction.USER_DEACTIVATED,
            target=user.username,
        )
        _reload()

    async def _delete(uid: int, name: str) -> None:
        confirmed = await confirm_dialog(
            t('users.delete_confirm').format(name=name),
            title=t('users.delete_title'),
            confirm_text=t('common.delete'),
            danger=True,
        )
        if not confirmed:
            return
        try:
            with get_session() as session:
                UserService(session).delete_user(uid)
        except ValueError as exc:
            await info_dialog(str(exc), title=t('users.not_possible'), danger=True)
            return
        audit_record(AuditAction.USER_DELETED, target=name)
        notify(t('users.deleted').format(name=name), type='warning')
        _reload()

    # Create dialog — labeled fields + tooltips, all three roles offered.
    def _open_create_dialog() -> None:
        with ui.dialog() as dialog, ui.column().classes('login-card gap-4'):
            ui.label(t('users.create_new')).classes('section-title')

            ui.label(t('users.col.user')).classes('field-label')
            username = ui.input(placeholder='jane.doe').props('outlined dense').classes('w-full') \
                .tooltip(t('users.tip.username'))

            ui.label(t('users.col.role')).classes('field-label')
            role = ui.select(
                options={
                    UserRole.USER.value: _role_label(UserRole.USER.value),
                    UserRole.OPERATOR.value: _role_label(UserRole.OPERATOR.value),
                    UserRole.ADMIN.value: _role_label(UserRole.ADMIN.value),
                },
                value=UserRole.USER.value,
            ).props('outlined dense').classes('w-full').tooltip(t('users.tip.role_field'))

            # Short description of the currently selected role
            role_hint = ui.label(t(_ROLE_DESC_KEY[UserRole.USER.value])).classes('text-xs text-muted')
            role.on_value_change(lambda e: role_hint.set_text(t(_ROLE_DESC_KEY.get(e.value,
                 _ROLE_DESC_KEY[UserRole.USER.value]))))

            with ui.element('div').classes(
                'w-full p-2').style('background: var(--faint); border-radius: 6px;'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('info', size='0.9rem').classes('text-muted')
                    ui.label(t('users.initial_pw')).classes('text-xs text-muted')

            async def create() -> None:
                name = (username.value or '').strip()
                if not name:
                    notify(t('users.enter_username'), type='warning')
                    return
                try:
                    with get_session() as session:
                        service = UserService(session)
                        if service.get_user_by_username(name) is not None:
                            notify(t('users.exists').format(name=name), type='negative')
                            return
                        _, initial_password = service.create_user(
                            name, role=UserRole(role.value))
                except ValueError as exc:
                    notify(str(exc), type='negative')
                    return
                audit_record(AuditAction.USER_CREATED, target=name, details=role.value)
                # The initial password is generated server-side (random,
                # one-time): show it to the admin exactly once.
                notify(t('users.created_pw').format(pw=initial_password or '—'),
                       type='positive')
                dialog.close()
                _reload()

            with ui.row().classes('w-full justify-end gap-2'):
                ui.button(t('common.cancel'), on_click=dialog.close).classes('button button-secondary')
                ui.button(t('common.create'), on_click=create).classes('button button-primary')

        dialog.open()

    with ui.row().classes('w-full justify-end mb-3'):
        ui.button(t('users.create'), icon='person_add', on_click=_open_create_dialog) \
            .classes('button button-primary')

    # Static header; the rows live in their own container so a per-cell
    # refresh never touches the header (and vice versa).
    with ui.column().classes('card w-full gap-0 p-0'):
        with ui.row().classes('w-full items-center px-4 py-3 label-text').style(
            'border-bottom: 1px solid var(--border, #e4e4e7);'
        ):
            ui.label(t('users.col.user')).classes('flex-1')
            ui.label(t('users.col.role')).style('width: 120px;')
            ui.label(t('users.col.source')).style('width: 140px;')
            ui.label(t('users.col.online')).style('width: 110px;')
            ui.label(t('users.col.activity')).style('width: 150px;')
            ui.label(t('users.col.status')).style('width: 120px;')
            ui.label(t('users.col.actions')).style('width: 180px;')
        rows = ui.column().classes('w-full gap-0')

    _reload()

    # Live updates: two SSE-driven counters — 'sessions_refresh_counter'
    # (login/logout/kick anywhere refreshes the online badges instantly)
    # and 'users_refresh_counter' (avatar/name change anywhere re-renders
    # the affected user cells immediately instead of waiting for the poll).
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
    # Fallback poll (SSE blind spots: browser closed without logout, stream
    # briefly reconnecting). Signature-based: _reload re-renders ONLY the
    # cells whose data moved — an unconditional full refresh every 15s made
    # the whole panel visibly blink although nothing changed.
    ui.timer(15.0, safe_auto_refresh(_reload))


# ================================================================== roles tab
def _roles_tab() -> None:
    """Read-only catalog of the three roles, with user counts (GET /roles)."""

    @ui.refreshable
    def roles_grid() -> None:
        with get_session() as api:
            roles = api.get('/roles')

        ui.label(t('roles.tab.hint')).classes('text-sm text-muted mb-4')

        with ui.row().classes('gap-4 items-start w-full'):
            for r in roles:
                badge_cls, badge_icon, label_key = _ROLE_BADGE.get(
                    r['name'], ('badge badge-default', 'person', 'users.role.user'))
                desc_key = _ROLE_DESC_KEY.get(r['name'], 'roles.desc.user')

                with ui.element('div').classes('card').style(
                        'flex:1;min-width:260px;padding:20px 22px;'):
                    with ui.row().classes('items-center gap-2 mb-3'):
                        with ui.element('span').classes(badge_cls).style('gap: 4px;'):
                            ui.icon(badge_icon, size='0.9rem')
                            ui.label(t(label_key))
                        if r['name'] == UserRole.ADMIN.value:
                            ui.icon('shield').style('font-size:1rem;color:#f59e0b') \
                                .tooltip(t('roles.tip.protected'))

                    ui.label(r.get('description') or t(desc_key)).classes('text-sm mb-4')

                    ui.element('div').classes('divider mt-0 mb-2')
                    with ui.row().classes('items-center justify-between'):
                        ui.label(t('roles.users_with_role')).classes('text-xs text-muted')
                        with ui.row().classes('items-center gap-1'):
                            ui.icon('group', size='0.9rem').classes('text-muted')
                            ui.label(str(r.get('user_count', 0))).classes('font-semi')

    roles_grid()
