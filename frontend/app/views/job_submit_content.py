"""Job submission page: ask the backend to run an action asynchronously.

POST /jobs answers 202 Accepted; execution happens on the worker fleet
(FOR UPDATE SKIP LOCKED). The page offers the registered job types with a
guided parameter form plus a free JSON payload, and the priority that
drives the claim order.
"""

from __future__ import annotations

import json

from nicegui import ui

from components.notifications import notify
from core.database import get_session
from services.i18n import t
from views._common import page_header

# Known job types registered in app.worker. Extend as handlers are added.
_JOB_TYPES = {
    'demo.sleep': {
        'label': 'demo.sleep — sleep for N seconds',
        'params_example': '{"seconds": 5}',
    },
}


def content() -> None:
    page_header(t('jobsubmit.title'), t('jobsubmit.subtitle'))

    result_box = {'job_id': None}

    with ui.row().classes('w-full items-start gap-4 no-wrap'):

        with ui.column().classes('card w-full gap-4 p-6').style('max-width: 560px;'):
            ui.label(t('jobsubmit.definition')).classes('section-title')

            job_type = ui.select(
                _JOB_TYPES, value='demo.sleep', label=t('jobsubmit.job_type')
            ).classes('w-full')

            ui.label(t('jobsubmit.params')).classes('label-text')
            params_input = ui.input(
                value='{"seconds": 5}', placeholder='{"seconds": 5}'
            ).classes('w-full').style('font-family: monospace;')

            def _apply_example() -> None:
                params_input.value = _JOB_TYPES[job_type.value]['params_example']
            job_type.on_value_change(lambda _: _apply_example())

            ui.label(t('jobsubmit.priority')).classes('label-text')
            priority = ui.slider(min=0, max=9, step=1, value=5).classes('w-full')
            ui.label(t('jobsubmit.priority_hint')).classes('text-xs text-muted')

            async def _submit() -> None:
                try:
                    params = json.loads(params_input.value or '{}')
                    if not isinstance(params, dict):
                        raise ValueError('Parameters must be a JSON object.')
                except (ValueError, TypeError) as exc:
                    notify(t('jobsubmit.invalid_params').format(err=exc), type='negative')
                    return

                try:
                    with get_session() as api:
                        job = api.post('/jobs', json={
                            'job_type': job_type.value,
                            'params': params,
                            'priority': priority.value,
                        })
                except Exception as exc:  # ApiError surfaced with a readable detail
                    notify(str(getattr(exc, 'detail', exc)), type='negative')
                    return
                result_box['job_id'] = job['id']
                notify(t('jobsubmit.queued_msg').format(id=job['id'], status=job['status']), type='positive')
                confirmation.refresh()

            ui.button(t('jobsubmit.submit'), icon='play_arrow', on_click=_submit).classes('button button-primary')

        @ui.refreshable
        def confirmation() -> None:
            with ui.column().classes('card w-full gap-2 p-6').style('max-width: 380px;'):
                ui.label(t('jobsubmit.last_submission')).classes('section-title')
                if result_box['job_id'] is None:
                    ui.label(t('jobsubmit.none_yet')).classes('text-muted')
                else:
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('check_circle', size='1.2rem').classes('text-positive')
                        ui.label(t('jobsubmit.queued_state').format(id=result_box['job_id']))
                    ui.button(t('jobsubmit.follow'), icon='list',
                              on_click=lambda: ui.navigate.to('/jobs')).props('flat no-caps')

        confirmation()
