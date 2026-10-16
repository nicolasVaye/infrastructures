"""TEMPORARY blank sub-pages used to stress-test the sidebar scrolling.

Eight dummy nav links point here so the nav bar overflows on short viewports
and the scroll fix (see .sidebar-nav-scroll in global-css.css) can be verified.
Demo 3 also exposes three sub-links (treeview branches, see add_nav_branch in
header.py) served by ``content(3, branch)``.
Remove this module together with the dummy links in header.py and the /demo-*
routes in main.py once validated.
"""

from nicegui import ui

from services.i18n import t
from views._common import page_header


def content(n: int, branch: str | int | None = None) -> None:
    if branch is None:
        page_header(t(f'nav.demo_{n}'), t('demo.subtitle'))
    else:
        page_header(t(f'nav.demo_{n}_{branch}'), t('demo.subtitle'))
