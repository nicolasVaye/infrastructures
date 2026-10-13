"""Per-user theme handling (light/dark), shared by every entry point.

The theme is persisted on the user account (users.theme) and applied in two
layers:

* ``ui.dark_mode`` toggles Quasar's dark mode (body.body--dark), which flips
  the CSS design tokens in global-css.css (cards, sidebar, header, fields).
* ``ui.colors`` must be re-applied too: Quasar primary/secondary colors are
  baked into components at build time and do NOT follow dark mode, so a page
  built with the light palette would keep dark-on-dark buttons after a
  live switch — hence the central :func:`apply` used by the layout, the
  login page and the /account preference card.
"""

from __future__ import annotations

from nicegui import app, ui

LIGHT_COLORS = {
    'primary': '#18181b', 'secondary': '#f4f4f5', 'positive': '#4caf50',
    'negative': '#ef4444', 'warning': '#f59e0b', 'info': '#3b82f6',
    'accent': '#e4e4e7',
}

DARK_COLORS = {
    'primary': '#e4e4e7', 'secondary': '#3f3f46', 'positive': '#4caf50',
    'negative': '#ef4444', 'warning': '#f59e0b', 'info': '#3b82f6',
    'accent': '#18181b',
}


def current() -> str:
    """The theme stored for this browser session ('light' by default)."""
    return app.storage.user.get('theme', 'light')


def apply(theme: str) -> None:
    """Apply a theme immediately: Quasar dark mode + Quasar color palette."""
    dark = theme == 'dark'
    ui.dark_mode(dark)
    ui.colors(**(DARK_COLORS if dark else LIGHT_COLORS))


def chart_colors() -> dict:
    """ECharts palette matching the active theme.

    Charts are built once per page render with these colors baked in; the
    /account theme selector reloads the page so charts pick up the new
    palette.
    """
    if current() == 'dark':
        return {
            'axis': '#2e2e34',       # axis lines
            'split': '#232329',       # horizontal grid lines
            'label': '#a1a1aa',       # axis + legend text
            'symbol': '#101013',       # border around point markers
            'tt_bg': '#1d1d22',        # tooltip background
            'tt_fg': '#fafafa',        # tooltip text
            'tt_border': '#3f3f46',    # tooltip border
            'emph': '#fafafa',         # emphasis labels
        }
    return {
        'axis': '#e4e4e7', 'split': '#f4f4f5', 'label': '#71717a',
        'symbol': '#ffffff', 'tt_bg': '#ffffff', 'tt_fg': '#09090b',
        'tt_border': '#e4e4e7', 'emph': '#09090b',
    }
