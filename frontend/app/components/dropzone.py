"""Reusable drag & drop upload zone styled to match the design system.

Wraps Quasar's uploader (via :func:`ui.upload`) so a file can be dropped on the
zone or selected by clicking it, entirely in Python. The visual (icon, title,
hint) is rendered underneath a transparent, full-cover uploader that captures
both clicks and native file drops.
"""

from __future__ import annotations

import asyncio
from typing import Callable

from nicegui import ui

from services import i18n


def dropzone(
    *,
    on_upload: Callable,
    max_file_size: int,
    accept: str = 'image/*',
    icon: str = 'cloud_upload',
    title_key: str = 'dropzone.title',
    hint_key: str = 'dropzone.hint',
) -> ui.upload:
    """Render a design-system dropzone and return the underlying ``ui.upload``.

    ``on_upload`` receives the standard NiceGUI upload event (``auto_upload``).
    Client-side rejections (wrong type or size, filtered by Quasar before any
    upload) are surfaced through ``on_rejected`` so the user gets a toast
    instead of a silently ignored file.
    """
    from components.notifications import notify
    from services.i18n import t

    def _on_rejected(_e) -> None:
        notify(t('settings.image_rejected'), type='warning')

    upload: ui.upload  # forward-declared for the wrapper closure

    async def _handle_upload(e) -> None:
        """Run the caller's handler, then reset the Quasar uploader.

        QUploader keeps uploaded files in its internal queue; re-selecting
        the same filename afterwards is rejected client-side as a duplicate
        (known Quasar/NiceGUI quirk). Resetting after each upload fixes it.
        """
        try:
            result = on_upload(e)
            if asyncio.iscoroutine(result):
                await result
        finally:
            upload.reset()

    with ui.element('div').classes('dropzone'):
        with ui.column().classes('dropzone__content'):
            ui.icon(icon).classes('dropzone__icon')
            i18n.bind(ui.label().classes('dropzone__title'), title_key)
            i18n.bind(ui.label().classes('dropzone__hint'), hint_key)
        upload = ui.upload(on_upload=_handle_upload, on_rejected=_on_rejected,
                            auto_upload=True, max_file_size=max_file_size)
        upload.props(f'accept="{accept}" flat').classes('dropzone__input')
    return upload
