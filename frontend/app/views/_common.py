"""Shared view building blocks used across the different content pages."""

from __future__ import annotations

from nicegui import ui

from services.i18n import t
from services.tz import format_local


def page_header(title: str, subtitle: str | None = None) -> None:
    """Render a consistent page title, optional subtitle and a divider."""
    with ui.column().classes('w-full gap-1 mt-4 mb-2'):
        ui.label(title).classes('page-title')
        if subtitle:
            ui.label(subtitle).classes('text-sm text-muted')
    ui.element('div').classes('divider mb-4')


def activity_sparkline(act: dict | None, display_tz) -> None:
    """24-bar activity sparkline: 10-minute buckets over the last 4 hours.

    ``act`` is one entry of GET /activity/users (Users tab, per user,
    cumulative across browsers) or /activity/sessions (Sessions tab, one
    browser/client per graph). ``None`` renders the neutral placeholder.
    """
    if act is None:
        ui.label('—').classes('text-xs text-muted')
        return
    bars = act.get('bars') or []
    total = sum(bars)
    peak = max(bars) if bars else 0
    last_at = act.get('last_activity')
    tip = t('activity.tooltip').format(
        n4h=total,
        n15=act.get('last15', 0),
        last=format_local(last_at, display_tz) if last_at else t('activity.none'),
    )
    with ui.element('div').style(
        'display: flex; align-items: flex-end; gap: 1px; '
        'height: 30px; width: 100px; cursor: default;'
    ).tooltip(tip):
        for count in bars:
            if count == 0:
                height, bg = 2, 'var(--border)'
            else:
                height = max(4, round(count / max(peak, 1) * 28))
                bg = 'var(--accent)'
            ui.element('div').style(
                f'width: 3px; height: {height}px; '
                f'background: {bg}; border-radius: 1px;'
            )


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
