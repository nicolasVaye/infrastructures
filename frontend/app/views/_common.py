"""Shared view building blocks used across the different content pages."""

from __future__ import annotations

from nicegui import ui


def page_header(title: str, subtitle: str | None = None) -> None:
    """Render a consistent page title, optional subtitle and a divider."""
    with ui.column().classes('w-full gap-1 mt-4 mb-2'):
        ui.label(title).classes('page-title')
        if subtitle:
            ui.label(subtitle).classes('text-sm text-muted')
    ui.element('div').classes('divider mb-4')


def safe_auto_refresh(fn) -> None:
    """Wrapper for timer-driven refreshes (auto-polling tables, boards…).

    After a logout — local or detected from another tab — the periodic
    timers may fire one last time with cleared/revoked credentials and raise
    an API 401. That is expected, not an error: swallow it instead of
    polluting the logs with tracebacks. Any other exception is re-raised.
    """
    from nicegui import app
    from shared.client.async_client import ApiError  # noqa: F401 — not re-exported by the package root

    def _safe() -> None:
        if not app.storage.user.get('authenticated', False):
            return
        try:
            fn()
        except ApiError as exc:
            if getattr(exc, 'status_code', None) != 401:
                raise
    return _safe
