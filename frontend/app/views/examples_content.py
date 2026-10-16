"""Examples hub: one tab per demo/example section.

The former top-level pages (Shipping, Production, Orders, Pallets, Packing,
Print Demo, Icons, Design System) each render inside a tab of this single
sub-page, keeping the nav bar short. Each tab renders the existing view module
unchanged; the tab bodies are built lazily (same pattern as the App Settings
hub — see views/settings_content.py).
"""

from nicegui import ui

from services.i18n import t
from views._common import page_header


def content() -> None:
    page_header(t('examples.title'), t('examples.subtitle'))

    # Lazy imports keep the module import graph flat. The tab BODIES are
    # built lazily too: NiceGUI executes every ui.tab_panel block when the
    # page renders, and building all eight at once would push every view
    # over the websocket before the first paint. Each body is built once,
    # on first activation of its tab; the default tab is built right away.
    from views import (
        design_system_content,
        icons_content,
        orders_content,
        packings_content,
        pallets_content,
        print_demo_content,
        production_content,
        shipping_content,
    )

    def _production() -> None:
        production_content.content(searchFilter='')

    _builders = {
        'shipping': shipping_content.content,
        'production': _production,
        'orders': orders_content.content,
        'pallets': pallets_content.content,
        'packing': packings_content.content,
        'print_demo': print_demo_content.content,
        'icons': icons_content.content,
        'design_system': design_system_content.content,
    }
    _icons = {
        'shipping': 'local_shipping',
        'production': 'precision_manufacturing',
        'orders': 'fact_check',
        'pallets': 'pallet',
        'packing': 'inventory_2',
        'print_demo': 'print',
        'icons': 'grid_view',
        'design_system': 'palette',
    }

    _slots: dict = {}
    _built: set[str] = set()

    def _activate(name: str) -> None:
        # The tabs element emits its initial value change BEFORE the panels
        # exist: ignore events for slots that are not created yet (the
        # default tab is built explicitly once the slots exist).
        slot = _slots.get(name)
        if slot is None or name in _built:
            return
        _built.add(name)
        with slot:
            _builders[name]()

    with ui.tabs().classes('tabs-bar').on_value_change(lambda e: _activate(e.value)) as tabs:
        for _name in _builders:
            ui.tab(name=_name, label=t(f'nav.{_name}'), icon=_icons[_name])

    with ui.tab_panels(tabs, value='shipping').classes('w-full'):
        for _name in _builders:
            with ui.tab_panel(_name):
                _slots[_name] = ui.column().classes('w-full')

    _activate('shipping')
