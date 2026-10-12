"""Job list page — Kanban board (Queued → Running → Succeeded/Failed/Cancelled).

Mirrors the packing page layout: a pipeline summary bar (total + per-status
counts), then one column per job status holding job cards, refreshed every 5s.
"""

from __future__ import annotations

from nicegui import app, ui

from components.dialogs import confirm_dialog, info_dialog
from components.notifications import notify
from core.database import get_session
from views._common import page_header, safe_auto_refresh

# Column styling (badge class, text class, icon, accent color)
_COL_STYLE = {
    'queued':    ('badge-default',  'text-muted',    'schedule',           '#71717a'),
    'running':   ('badge-info',     'text-info',     'progress_activity',  '#60a5fa'),
    'succeeded': ('badge-success',  'text-positive', 'check_circle',       '#4ade80'),
    'failed':    ('badge-negative', 'text-negative', 'error',              '#f87171'),
    'cancelled': ('badge-warning',  'text-warning',  'cancel',             '#fbbf24'),
}

_COL_TITLE = {
    'queued':    ('Queued',    'Waiting for a worker to claim it'),
    'running':   ('Running',   'Currently executed by a worker'),
    'succeeded': ('Succeeded',  'Finished without error'),
    'failed':    ('Failed',     'Terminated with an error'),
    'cancelled': ('Cancelled',  'Aborted before completion'),
}

_COL_ORDER = ['queued', 'running', 'succeeded', 'failed', 'cancelled']

# Icon shown next to the job type on a card
_TYPE_ICONS = {'demo.sleep': 'bedtime'}


def content() -> None:
    page_header('Jobs', 'Asynchronous jobs executed by the worker fleet')

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
                ui.label('Total jobs').classes('label-text mb-1')
                ui.label(str(total)).classes('text-2xl font-bold text-info')
                ui.label('last 200 submissions').classes('text-xs text-muted mt-1')

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
                        ui.label(_COL_TITLE[status][0]).classes('label-text')
                    ui.label(str(cnt)).classes(f'text-2xl font-bold {text_cls}')
                    ui.label(f'{pct}% of jobs').classes('text-xs text-muted mt-1')

        # -- Filter banner --------------------------------------------------
        if selected['status'] is not None:
            with ui.row().classes('w-full items-center gap-2 mb-2'):
                ui.icon('filter_alt', size='1rem').classes('text-info')
                ui.label(f'Filtered on: {selected["status"]}').classes('text-sm')
                ui.button(icon='clear', on_click=lambda: (selected.update(status=None),
                                                          board.refresh())
                          ).props('flat dense round').tooltip('Clear filter')

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
                            ui.label(_COL_TITLE[status][0]).classes('font-semi text-base')
                        ui.label(str(len(column_jobs))).classes(f'badge {badge_cls}')

                    # Job cards
                    with ui.column().classes('gap-3 w-full'):
                        if not column_jobs:
                            ui.label(_COL_TITLE[status][1]).classes(
                                'text-xs text-faint text-center py-6')

                        for j in column_jobs:
                            with ui.element('div').classes('card').style('padding:16px 18px'):
                                # Card top: ID + priority
                                with ui.row().classes('items-center justify-between mb-2'):
                                    ui.label(f"#{j['id']}").classes('font-semi text-sm')
                                    with ui.row().classes('items-center gap-1'):
                                        ui.icon('low_priority').style(
                                            'font-size:12px;color:var(--faint-fg)')
                                        ui.label(f"p{j['priority']}").classes('text-xs text-faint')

                                # Job type
                                with ui.row().classes('items-center gap-2 mb-1'):
                                    ui.icon(_TYPE_ICONS.get(j['job_type'], 'task_alt'),
                                            size='0.9rem').classes('text-muted')
                                    ui.label(j['job_type']).classes('text-sm font-medium')

                                # Result or error
                                if j.get('error'):
                                    ui.label(j['error'][:110]).classes(
                                        'text-xs text-negative truncate mb-2')
                                elif j.get('result'):
                                    ui.label(str(j['result'])[:110]).classes(
                                        'text-xs text-muted truncate mb-2')
                                else:
                                    ui.label(_COL_TITLE[status][1]).classes(
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

                                # Footer: params + cancel
                                ui.element('div').classes('divider mt-0 mb-2')
                                with ui.row().classes('items-center justify-between'):
                                    ui.label(str(j.get('params') or '{}')[:40]).classes(
                                        'text-xs text-faint font-mono truncate')
                                    if status in ('queued', 'running'):
                                        async def _cancel(job_id: int = j['id']) -> None:
                                            confirmed = await confirm_dialog(
                                                f'Cancel job #{job_id}?', title='Cancel job',
                                                danger=True)
                                            if not confirmed:
                                                return
                                            try:
                                                with get_session() as api:
                                                    api.post(f'/jobs/{job_id}/cancel')
                                            except Exception as exc:
                                                await info_dialog(
                                                    str(getattr(exc, 'detail', exc)),
                                                    title='Not possible', danger=True)
                                                return
                                            notify(f'Job #{job_id} cancelled', type='warning')
                                            board.refresh()

                                        ui.button('Cancel', color='white', on_click=_cancel) \
                                            .props('flat no-caps') \
                                            .classes('button button-outline button-sm')

        if not jobs:
            with ui.column().classes('card w-full items-center gap-2 p-8 mt-2'):
                ui.icon('inbox', size='2rem').classes('text-muted')
                ui.label('No job submitted yet — use the "Submit job" page.').classes('text-muted')

    with ui.row().classes('w-full justify-end'):
        ui.button('Submit a new job', icon='add',
                  on_click=lambda: ui.navigate.to('/jobs/new')).props('outline no-caps')

    board()
    ui.timer(5.0, safe_auto_refresh(board.refresh))

    # Live push: the SSE listener (see services/events_client.py) bumps this
    # client-storage counter on every job_updated event — refresh the board
    # immediately instead of waiting for the 5s poll.
    seen = {'counter': app.storage.client.get('jobs_refresh_counter', 0)}

    def _on_event() -> None:
        counter = app.storage.client.get('jobs_refresh_counter', 0)
        if counter != seen['counter']:
            seen['counter'] = counter
            safe_auto_refresh(board.refresh)()

    ui.timer(1.0, _on_event)
