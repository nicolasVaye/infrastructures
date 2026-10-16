"""Reusable pagination footer for the admin tables.

All three admin tables (Users, Sessions, Audit) render one page of rows at
a time: the pager states the visible range and moves between pages. It
renders nothing beyond a count when everything fits on one page — small
deployments keep the clean footer they had before pagination existed.
"""

from __future__ import annotations

from typing import Callable

from nicegui import ui

from services.i18n import t


def pager(total: int, page: int, size: int, on_change: Callable[[int], None]) -> None:
    """Render 'Showing from–to of total' + prev/next page controls.

    ``on_change(page)`` receives the new 1-based page number. When a single
    page holds everything, only the range label is shown (no dead buttons).
    """
    if total <= size:
        if total:
            ui.label(t('common.pager.showing').format(
                frm=1, to=total, total=total)).classes('text-xs text-muted')
        return
    pages = (total + size - 1) // size
    page = max(1, min(page, pages))
    start = (page - 1) * size + 1
    end = min(page * size, total)

    with ui.row().classes('w-full items-center justify-end gap-2 pt-2 no-wrap'):
        ui.label(t('common.pager.showing').format(
            frm=start, to=end, total=total)).classes('text-xs text-muted')
        prev = ui.button(icon='chevron_left',
                         on_click=lambda: on_change(max(1, page - 1)))
        prev.props('flat dense outline no-caps').classes('button button-ghost') \
            .tooltip(t('common.pager.prev'))
        if page <= 1:
            prev.disable()
        ui.label(f'{page} / {pages}').classes('text-xs text-muted')
        nxt = ui.button(icon='chevron_right',
                        on_click=lambda: on_change(min(pages, page + 1)))
        nxt.props('flat dense outline no-caps').classes('button button-ghost') \
            .tooltip(t('common.pager.next'))
        if page >= pages:
            nxt.disable()
