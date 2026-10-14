"""Job list page — Kanban board (Queued → Running → Succeeded/Failed/Cancelled).

Mirrors the packing page layout: a pipeline summary bar (total + per-status
counts), then one column per job status holding job cards, refreshed every 5s.
"""

from __future__ import annotations

import json

from nicegui import app, ui

from components.dialogs import confirm_dialog, info_dialog
from components.notifications import notify
from core.database import get_session
from services.i18n import t
from views._common import page_header, safe_auto_refresh

# Column styling (badge class, text class, icon, accent color)
_COL_STYLE = {
    'queued':    ('badge-default',  'text-muted',    'schedule',           '#71717a'),
    # 'autorenew' rather than 'progress_activity': the latter is a recent
    # Material Symbols name missing from the Material Icons font NiceGUI loads.
    'running':   ('badge-info',     'text-info',     'autorenew',          '#60a5fa'),
    'succeeded': ('badge-success',  'text-positive', 'check_circle',       '#4ade80'),
    'failed':    ('badge-negative', 'text-negative', 'error',              '#f87171'),
    'cancelled': ('badge-warning',  'text-warning',  'cancel',             '#fbbf24'),
}

# status -> (title key, description key): translated at render time so a
# live language switch shows up on the next board refresh.
_COL_TITLE = {
    'queued':    ('jobs.col.queued',    'jobs.col.queued_desc'),
    'running':   ('jobs.col.running',   'jobs.col.running_desc'),
    'succeeded': ('jobs.col.succeeded', 'jobs.col.succeeded_desc'),
    'failed':    ('jobs.col.failed',    'jobs.col.failed_desc'),
    'cancelled': ('jobs.col.cancelled', 'jobs.col.cancelled_desc'),
}

_COL_ORDER = ['queued', 'running', 'succeeded', 'failed', 'cancelled']

# Icon shown next to the job type on a card
_TYPE_ICONS = {'demo.sleep': 'bedtime',
               'maintenance.cleanup_sessions': 'cleaning_services'}

# Human description per job type: (description key, params docs key)
_TYPE_DESC = {
    'demo.sleep': ('jobs.type.demo_sleep', 'jobs.params.demo_sleep'),
    'maintenance.cleanup_sessions': ('jobs.type.cleanup_sessions', 'jobs.params.cleanup_sessions'),
}

# Human-readable names for job types (falls back to the raw type id).
_TYPE_LABEL = {
    'demo.sleep': 'jobs.type_name.demo_sleep',
    'maintenance.cleanup_sessions': 'jobs.type_name.cleanup_sessions',
}


def _type_name(job_type: str) -> str:
    """Translate a job type id into a short, human-readable label."""
    return t(_TYPE_LABEL[job_type]) if job_type in _TYPE_LABEL else job_type


def content() -> None:
    page_header(t('jobs.title'), t('jobs.subtitle'))

    selected = {'status': None}  # None = all columns

    @ui.refreshable
    def board() -> None:
        # Refreshables run in a background task: guard the fetch itself so a
        # revoked session (logout in another tab, self-kick) doesn't raise.
        from shared.client.async_client import ApiError
        try:
            with get_session() as api:
                jobs = api.get('/jobs', params={'limit': 200})
        except ApiError as exc:
            if getattr(exc, 'status_code', None) == 401:
                return  # session revoked: heartbeat handles the redirect
            raise
        by_status: dict[str, list] = {s: [] for s in _COL_ORDER}
        for j in jobs:
            by_status.setdefault(j['status'], []).append(j)
        total = len(jobs)

        # -- Pipeline summary bar -----------------------------------------
        with ui.row().classes('gap-0 flex-wrap mb-6 w-full').style(
                'border:1px solid var(--border);border-radius:var(--radius-lg);overflow:hidden'):
            with ui.element('div').style(
                    'flex:1;min-width:160px;padding:18px 24px;border-right:1px solid var(--border)'):
                ui.label(t('jobs.total')).classes('label-text mb-1')
                ui.label(str(total)).classes('text-2xl font-bold text-info')
                ui.label(t('jobs.last_n')).classes('text-xs text-muted mt-1')

            for status in _COL_ORDER:
                badge_cls, text_cls, icon, color = _COL_STYLE[status]
                cnt = len(by_status[status])
                pct = int(cnt / total * 100) if total else 0
                is_last = status == 'cancelled'
                with ui.element('div').style(
                        f'flex:1;min-width:140px;padding:18px 24px;cursor:pointer;'
                        f'{"" if is_last else "border-right:1px solid var(--border)"}'
                ).on('click', lambda _, s=status: (selected.update(status=None)
                                                   if selected['status'] == s
                                                   else selected.update(status=s), board.refresh())):
                    with ui.row().classes('items-center gap-2 mb-1'):
                        ui.icon(icon).style(f'font-size:1rem;color:{color}')
                        ui.label(t(_COL_TITLE[status][0])).classes('label-text')
                    ui.label(str(cnt)).classes(f'text-2xl font-bold {text_cls}')
                    ui.label(t('jobs.pct').format(pct=pct)).classes('text-xs text-muted mt-1')

        # -- Filter banner --------------------------------------------------
        if selected['status'] is not None:
            with ui.row().classes('w-full items-center gap-2 mb-2'):
                ui.icon('filter_alt', size='1rem').classes('text-info')
                ui.label(t('jobs.filtered_on').format(status=selected['status'])).classes('text-sm')
                ui.button(icon='clear', on_click=lambda: (selected.update(status=None),
                                                          board.refresh())
                          ).props('flat dense round').tooltip(t('jobs.clear_filter'))

        # -- Kanban columns -------------------------------------------------
        visible = [selected['status']] if selected['status'] else _COL_ORDER
        with ui.row().classes('gap-4 items-start w-full').style('overflow-x: auto;'):
            for status in visible:
                badge_cls, text_cls, col_icon, col_color = _COL_STYLE[status]
                column_jobs = by_status[status]

                with ui.element('div').style(
                        f'flex:1;min-width:260px;padding:14px;border-radius:var(--radius-lg);'
                        f'border:1px solid var(--border);background:var(--faint)'):
                    # Column header
                    with ui.row().classes('items-center justify-between mb-4').style(
                            f'padding-bottom:12px;border-bottom:2px solid {col_color}'):
                        with ui.row().classes('items-center gap-2'):
                            ui.icon(col_icon).style(f'font-size:1.1rem;color:{col_color}')
                            ui.label(t(_COL_TITLE[status][0])).classes('font-semi text-base')
                        ui.label(str(len(column_jobs))).classes(f'badge {badge_cls}')

                    # Job cards
                    with ui.column().classes('gap-3 w-full'):
                        if not column_jobs:
                            ui.label(t(_COL_TITLE[status][1])).classes(
                                'text-xs text-faint text-center py-6')

                        for j in column_jobs:
                            with ui.element('div').classes('card').style('padding:16px 18px'):
                                # Card top: ID + priority
                                with ui.row().classes('items-center justify-between mb-2'):
                                    ui.label(f"#{j['id']}").classes('font-semi text-sm')
                                    with ui.row().classes('items-center gap-1') as _prio:
                                        _prio.tooltip(t('jobs.priority_hint').format(p=j['priority']))
                                        ui.icon('low_priority').style(
                                            'font-size:12px;color:var(--faint-fg)') \
                                            .tooltip(t('jobs.priority_hint').format(p=j['priority']))
                                        ui.label(f"p{j['priority']}").classes('text-xs text-faint') \
                                            .tooltip(t('jobs.priority_hint').format(p=j['priority']))

                                # Job type
                                with ui.row().classes('items-center gap-2 mb-1'):
                                    ui.icon(_TYPE_ICONS.get(j['job_type'], 'task_alt'),
                                            size='0.9rem').classes('text-muted')
                                    ui.label(_type_name(j['job_type'])).classes('text-sm font-medium')

                                # What this job does (known types)
                                desc_key = _TYPE_DESC.get(j['job_type'], (None, None))[0]
                                if desc_key:
                                    ui.label(t(desc_key)).classes('text-xs text-muted mb-1')

                                # Result or error
                                if j.get('error'):
                                    ui.label(j['error'][:110]).classes(
                                        'text-xs text-negative truncate mb-2')
                                elif j.get('result'):
                                    ui.label(str(j['result'])[:110]).classes(
                                        'text-xs text-muted truncate mb-2')
                                else:
                                    ui.label(t(_COL_TITLE[status][1])).classes(
                                        'text-xs text-muted mb-2')

                                # Chips: created by + timestamps
                                with ui.row().classes('gap-2 flex-wrap mb-3'):
                                    with ui.element('span').classes('chip'):
                                        ui.icon('person').style('font-size:11px;margin-right:3px')
                                        ui.label(j.get('created_by') or '—')
                                    if j.get('finished_at'):
                                        with ui.element('span').classes('chip'):
                                            ui.icon('schedule').style(
                                                'font-size:11px;margin-right:3px')
                                            ui.label(str(j['finished_at'])[:19])

                                # Footer: params + details/cancel
                                ui.element('div').classes('divider mt-0 mb-2')
                                with ui.row().classes('items-center justify-between'):
                                    ui.label(str(j.get('params') or '{}')[:40]).classes(
                                        'text-xs text-faint font-mono truncate')
                                    with ui.row().classes('items-center gap-0'):
                                        ui.button(icon='info', on_click=lambda _, job=j:
                                                  _show_details(job)) \
                                            .props('flat dense round').tooltip(t('jobs.details'))

                                        if status in ('queued', 'running'):
                                            async def _cancel(job_id: int = j['id']) -> None:
                                                confirmed = await confirm_dialog(
                                                    t('jobs.cancel_confirm').format(id=job_id),
                                                    title=t('jobs.cancel_title'), danger=True)
                                                if not confirmed:
                                                    return
                                                try:
                                                    with get_session() as api:
                                                        api.post(f'/jobs/{job_id}/cancel')
                                                except Exception as exc:
                                                    await info_dialog(
                                                        str(getattr(exc, 'detail', exc)),
                                                        title=t('jobs.not_possible'), danger=True)
                                                    return
                                                notify(t('jobs.cancelled_msg').format(id=job_id), type='warning')
                                                board.refresh()

                                            ui.button(t('jobs.cancel'), color='white', on_click=_cancel) \
                                                .props('flat no-caps') \
                                                .classes('button button-outline button-sm')

        if not jobs:
            with ui.column().classes('card w-full items-center gap-2 p-8 mt-2'):
                ui.icon('inbox', size='2rem').classes('text-muted')
                ui.label(t('jobs.empty')).classes('text-muted')

    def _show_details(job: dict) -> None:
        """Everything about one job: what it does, its params and result."""
        with ui.dialog() as dialog, ui.column().classes('login-card gap-3') \
                .style('min-width: 480px; max-width: 640px;'):
            with ui.row().classes('items-center gap-2'):
                ui.icon(_TYPE_ICONS.get(job['job_type'], 'task_alt'), size='1.1rem') \
                    .classes('text-muted')
                ui.label(f"#{job['id']} — {_type_name(job['job_type'])}").classes('section-title')

            desc_key, params_key = _TYPE_DESC.get(job['job_type'], (None, None))
            if desc_key:
                ui.label(t(desc_key)).classes('text-sm')
            if params_key:
                with ui.element('div').classes('w-full p-2').style(
                        'background: var(--faint); border-radius: 6px;'):
                    ui.label(t(params_key)).classes('text-xs text-muted')

            for label, value in [
                ('status', job.get('status')),
                ('priority', job.get('priority')),
                ('created_by', job.get('created_by')),
                ('created_at', job.get('created_at')),
                ('started_at', job.get('started_at')),
                ('finished_at', job.get('finished_at')),
            ]:
                with ui.row().classes('w-full justify-between no-wrap'):
                    ui.label(label).classes('text-xs text-muted')
                    ui.label(str(value)).classes('text-xs font-mono')

            ui.label(t('jobs.params_label')).classes('field-label mb-0 mt-2')
            ui.html(f'<pre style="margin:0;font-size:12px;">'
                    f'{json.dumps(job.get("params") or {}, indent=2)}</pre>')

            if job.get('result'):
                ui.label(t('jobs.result_label')).classes('field-label mb-0 mt-2')
                ui.html(f'<pre style="margin:0;font-size:12px;">'
                        f'{json.dumps(job["result"], indent=2)}</pre>')
            if job.get('error'):
                ui.label(t('jobs.error_label')).classes('field-label mb-0 mt-2')
                ui.label(job['error']).classes('text-xs text-negative')

            with ui.row().classes('w-full justify-end'):
                ui.button(t('common.close'), on_click=dialog.close).classes('button button-secondary')
        dialog.open()

    # -- Schedules (admin): what runs periodically, editable -------------------
    @ui.refreshable
    def schedules_panel() -> None:
        from shared.client.async_client import ApiError as _ApiError
        try:
            with get_session() as api:
                schedules = api.get('/schedules')
        except _ApiError as exc:
            if getattr(exc, 'status_code', None) == 403:
                return  # not an admin: hide the panel silently
            raise

        with ui.element('div').classes('card w-full gap-0 p-0 mb-6'):
            with ui.row().classes('w-full items-center justify-between px-4 py-3') \
                    .style('border-bottom: 1px solid var(--border);'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('schedule_send', size='1rem').classes('text-muted')
                    ui.label(t('jobs.schedules_title')).classes('card-title')
                ui.label(t('jobs.schedules_desc')).classes('text-xs text-muted')

            for sc in schedules:
                with ui.row().classes('w-full items-center px-4 py-3 no-wrap') \
                        .style('border-bottom: 1px solid var(--border);'):
                    with ui.column().classes('flex-1 gap-0 min-w-0'):
                        with ui.row().classes('items-center gap-2'):
                            ui.icon(_TYPE_ICONS.get(sc['job_type'], 'task_alt'),
                                    size='0.9rem').classes('text-muted')
                            ui.label(_type_name(sc['job_type'])).classes('text-sm font-medium truncate')
                            desc_key = _TYPE_DESC.get(sc['job_type'], (None, None))[0]
                            if desc_key:
                                ui.label(t(desc_key)).classes('text-xs text-muted truncate')
                    with ui.element('span').classes('chip font-mono'):
                        ui.icon('schedule').style('font-size:11px;margin-right:3px')
                        ui.label(sc['cron'])
                    with ui.element('span').classes(
                        'badge ' + ('badge-success' if sc['enabled'] else 'badge-default')):
                        ui.label(t('jobs.enabled') if sc['enabled'] else t('jobs.disabled'))
                    ui.label(str(sc.get('params') or '{}')[:30]).classes(
                        'text-xs text-faint font-mono truncate').style('width: 110px;')

                    def _patch(sc_: dict = sc, **changes) -> None:
                        with get_session() as api:
                            api.patch(f"/schedules/{sc_['id']}", json=changes)
                        schedules_panel.refresh()
                        board.refresh()

                    def _run_now(sc_: dict = sc) -> None:
                        with get_session() as api:
                            api.post('/jobs', json={'job_type': sc_['job_type'],
                                                    'params': sc_.get('params') or {}})
                        notify(t('jobs.run_now_msg').format(type=_type_name(sc_['job_type'])),
                               type='positive')
                        board.refresh()

                    def _edit_schedule(sc_: dict = sc) -> None:
                        with ui.dialog() as dialog, ui.column().classes('login-card gap-3') \
                                .style('min-width: 420px;'):
                            ui.label(t('jobs.edit_schedule').format(id=sc_['id'])) \
                                .classes('section-title')

                            ui.label(t('jobs.cron_label')).classes('field-label')
                            cron = ui.input(value=sc_['cron'], placeholder='0 3 * * *') \
                                .classes('w-full').style('font-family: monospace;')
                            ui.label(t('jobs.cron_hint')).classes('text-xs text-muted')

                            ui.label(t('jobs.params_label')).classes('field-label')
                            import json as _json
                            params = ui.textarea(
                                value=_json.dumps(sc_.get('params') or {}, indent=2),
                            ).classes('w-full').style('font-family: monospace;')

                            enabled = ui.switch(t('jobs.enabled'), value=sc_['enabled'])

                            async def save() -> None:
                                changes: dict = {}
                                if cron.value.strip() and cron.value != sc_['cron']:
                                    changes['cron'] = cron.value.strip()
                                if params.value != _json.dumps(sc_.get('params') or {}, indent=2):
                                    try:
                                        import json as _j
                                        changes['params'] = _j.loads(params.value or '{}')
                                    except Exception:
                                        notify(t('jobs.invalid_json'), type='negative')
                                        return
                                if enabled.value != sc_['enabled']:
                                    changes['enabled'] = enabled.value
                                if not changes:
                                    dialog.close()
                                    return
                                try:
                                    with get_session() as api:
                                        api.patch(f"/schedules/{sc_['id']}", json=changes)
                                except Exception as exc:
                                    await info_dialog(str(getattr(exc, 'detail', exc)),
                                                      title=t('jobs.not_possible'), danger=True)
                                    return
                                notify(t('jobs.schedule_saved'), type='positive')
                                dialog.close()
                                schedules_panel.refresh()

                            with ui.row().classes('w-full justify-end gap-2'):
                                ui.button(t('common.cancel'), on_click=dialog.close) \
                                    .classes('button button-secondary')
                                ui.button(t('common.save'), on_click=save) \
                                    .classes('button button-primary')
                        dialog.open()

                    async def _delete_schedule(sc_: dict = sc) -> None:
                        confirmed = await confirm_dialog(
                            t('jobs.delete_schedule_confirm').format(id=sc_['id']),
                            title=t('jobs.delete_schedule_title'), danger=True)
                        if not confirmed:
                            return
                        with get_session() as api:
                            api.delete(f"/schedules/{sc_['id']}")
                        notify(t('jobs.schedule_deleted'), type='warning')
                        schedules_panel.refresh()

                    with ui.row().classes('items-center gap-1'):
                        ui.button(icon=sc['enabled'] and 'pause' or 'play_arrow',
                                  on_click=lambda _, s=sc: _patch(s,
                                      enabled=not s['enabled'])) \
                            .props('flat dense round').tooltip(
                                t('jobs.tip.disable') if sc['enabled'] else t('jobs.tip.enable'))
                        ui.button(icon='bolt', on_click=lambda _, s=sc: _run_now(s)) \
                            .props('flat dense round').tooltip(t('jobs.run_now'))
                        ui.button(icon='edit', on_click=lambda _, s=sc: _edit_schedule(s)) \
                            .props('flat dense round').tooltip(t('jobs.tip.edit'))
                        ui.button(icon='delete', on_click=lambda _, s=sc: _delete_schedule(s)) \
                            .props('flat dense round color=negative') \
                            .tooltip(t('jobs.tip.delete'))

    # -- Submit job dialog (admin): replaces the old /jobs/new page ----------
    _PARAMS_EXAMPLES = {'demo.sleep': '{"seconds": 5}',
                        'maintenance.cleanup_sessions': '{"keep_days": 7}'}

    def _open_submit_dialog() -> None:
        """Modal form: job type, JSON params, priority — same style as the
        users 'create user' dialog. Lives OUTSIDE any refreshable, so a board
        refresh can never destroy it."""
        with ui.dialog() as dialog, ui.column().classes('login-card gap-3') \
                .style('min-width: 480px; max-width: 640px;'):
            ui.label(t('jobs.submit_new')).classes('section-title')

            type_select = ui.select(
                {jt: _type_name(jt) for jt in _TYPE_LABEL},
                value='demo.sleep', label=t('jobsubmit.job_type'),
            ).classes('w-full')

            desc_key, params_key = _TYPE_DESC.get(type_select.value, (None, None))

            def _update_example(e) -> None:
                params_input.set_value(_PARAMS_EXAMPLES.get(e.value, '{}'))
                # swap the inline description + params docs on type change
                desc_el.set_text(t(_TYPE_DESC.get(e.value, (None, None))[0])
                                 if _TYPE_DESC.get(e.value, (None, None))[0] else '')
                params_el.set_text(t(_TYPE_DESC.get(e.value, (None, None))[1])
                                   if _TYPE_DESC.get(e.value, (None, None))[1] else '')

            type_select.on_value_change(_update_example)

            ui.label(t('jobsubmit.params')).classes('field-label mb-0')
            params_input = ui.textarea(
                value=_PARAMS_EXAMPLES.get(type_select.value, '{}'),
            ).classes('w-full').style('font-family: monospace;')
            desc_el = ui.label(t(desc_key) if desc_key else '').classes('text-xs text-muted')
            params_el = ui.label(t(params_key) if params_key else '').classes('text-xs text-faint')

            priority = ui.number(
                label=t('jobsubmit.priority'), value=5, min=0, max=9, precision=0,
            ).classes('w-full')
            ui.label(t('jobsubmit.priority_hint')).classes('text-xs text-muted')

            def _submit() -> None:
                try:
                    params = json.loads(params_input.value or '{}')
                except ValueError:
                    notify(t('jobs.invalid_json'), type='negative')
                    return
                with get_session() as api:
                    job = api.post('/jobs', json={'job_type': type_select.value,
                                                  'params': params,
                                                  'priority': int(priority.value or 0)})
                notify(t('jobsubmit.queued_msg').format(id=job['id'], status=job['status']),
                       type='positive')
                dialog.close()
                _guarded_refresh()

            with ui.row().classes('w-full justify-end gap-2'):
                ui.button(t('common.cancel'), color='white', on_click=dialog.close) \
                    .classes('button button-secondary')
                ui.button(t('jobsubmit.submit'), icon='play_arrow', on_click=_submit) \
                    .classes('button button-primary')
        dialog.open()

    with ui.row().classes('w-full justify-end'):
        ui.button(t('jobs.submit_new'), icon='add',
                  on_click=_open_submit_dialog).classes('button button-primary')

    schedules_panel()
    # A refresh while a job-details dialog is open would close it (the dialog
    # lives inside the refreshable). Track open dialogs globally and skip the
    # refresh while one is open; the next event after it closes catches up.
    open_dialogs = {'count': 0}

    def _guarded_refresh() -> None:
        if open_dialogs['count'] > 0:
            return
        safe_auto_refresh(board.refresh)()

    original_open, original_close = ui.dialog.open, ui.dialog.close

    def _tracked_open(self, *args, **kwargs):
        open_dialogs['count'] += 1
        return original_open(self, *args, **kwargs)

    def _tracked_close(self, *args, **kwargs):
        result = original_close(self, *args, **kwargs)
        open_dialogs['count'] = max(0, open_dialogs['count'] - 1)
        return result

    ui.dialog.open, ui.dialog.close = _tracked_open, _tracked_close

    board()

    # NO polling timer: the board refreshes only when a real change happens.
    # The SSE listener (see services/events_client.py) bumps the
    # 'jobs_refresh_counter' on every job_updated event (submitted, claimed,
    # started, finished, cancelled — from this tab AND from other users,
    # workers or backend replicas) and 'schedules_refresh_counter' when a
    # schedule is created/edited/deleted. The 1s timer below is a cheap
    # counter check that only rebuilds on change — tooltips and dialogs are
    # never disturbed by periodic redraws.
    seen = {'jobs': app.storage.user.get('jobs_refresh_counter', 0),
            'schedules': app.storage.user.get('schedules_refresh_counter', 0)}

    def _on_event() -> None:
        jobs = app.storage.user.get('jobs_refresh_counter', 0)
        schedules = app.storage.user.get('schedules_refresh_counter', 0)
        if schedules != seen['schedules']:
            seen['schedules'] = schedules
            schedules_panel.refresh()
        if jobs != seen['jobs']:
            seen['jobs'] = jobs
            _guarded_refresh()

    ui.timer(1.0, _on_event)

