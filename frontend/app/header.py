"""Application shell: header bar, collapsible sidebar and active-link tracking."""

from contextlib import contextmanager
from components.notifications import notify, notify_ongoing
from components.sidebar_hint import sidebar_hint
from nicegui import ui, app
from core.security import logout, current_user
from services import i18n


# Sections surfaced through the mobile burger sheet, beyond the 3 primary tabs
_SHEET_SECTIONS = [
    ('nav.orders',        'fact_check',  '/orders'),
    ('nav.pallets',       'pallet',      '/pallets'),
    ('nav.packing',       'inventory_2', '/packing'),
    ('nav.print_demo',    'print',       '/print-demo'),
    ('nav.icons',         'grid_view',   '/icons'),
    ('nav.design_system', 'palette',     '/design-system'),
]


@contextmanager
def frame(title: str, version: str, get_logo_func=None):

    # Header toolbar
    # fixed=True pins the header to the viewport so the sub pages never scroll
    # under/over it: Quasar then reserves the header height at the top of the
    # page container and scrolling happens strictly below the header.
    with ui.header(fixed=True).classes(replace='row items-center h-20 justify-start') as header:
        ui.label("").classes('pr-4 md:pr-8')

        # Application logo, served by GET /logo (custom logo from the admin
        # settings, or the bundled asset). Refreshable so every tab live-
        # reloads it when an admin uploads a new one (logo_version counter,
        # same pattern as the account widget below).
        @ui.refreshable
        def logo_widget() -> None:
            v = app.storage.user.get('logo_version', 0)
            ui.html(
                '<div style="width: 4rem; height: 4rem;'
                f'background-image: url(\'/logo?v={v}\');'
                'background-size: contain; background-repeat: no-repeat;'
                'background-position: center;"></div>',
                sanitize=False,
            )
        logo_widget()

        ui.label("").classes("pr-2")
        ui.label(title).classes('app-name')
        ui.space()
        # Account button rendered as a refreshable widget: the account page
        # (this tab) and the profile-change detector (other tabs) can simply
        # call .refresh() to re-render name and avatar from the session
        # storage — pure Python, no page reload, no JavaScript.
        @ui.refreshable
        def account_widget() -> None:
            u = current_user()
            # The avatar comes from GET /avatar (fetched from the DB on each
            # render); the session cookie only carries the version counter,
            # used as a cache-buster when the image changes.
            if app.storage.user.get('has_avatar'):
                v = app.storage.user.get('avatar_version', 0)
                icon = f'img:/avatar?v={v}'
            else:
                icon = 'account_circle'
            name = (u.display_name or u.username) if u else 'Guest'
            with ui.dropdown_button('', icon=icon).classes('mr-4 header-account-btn') \
                    .props('flat push no-icon-animation auto-close unelevated'):
                with ui.element('div').classes('account-dropdown'):
                    ui.label(name).classes('account-name')
                    ui.element('div').classes('account-separator')
                    with ui.row().classes('account-menu-item').style('min-height: 48px;').on('click', lambda: ui.navigate.to('/account')):
                        ui.icon('person').classes('account-icon')
                        i18n.bind(ui.label(i18n.t('account.account')), 'account.account')
                    if u and u.is_admin:
                        with ui.row().classes('account-menu-item').style('min-height: 48px;').on('click', lambda: ui.navigate.to('/settings')):
                            ui.icon('tune').classes('account-icon')
                            i18n.bind(ui.label(i18n.t('appsettings.title')), 'appsettings.title')
                    ui.element('div').classes('account-separator')
                    with ui.row().classes('account-menu-item logout').style('min-height: 48px;').on('click', logout):
                        ui.icon('logout').classes('account-icon')
                        i18n.bind(ui.label(i18n.t('account.logout')), 'account.logout')

        account_widget()
        app.storage.client['header_account_refresh'] = account_widget.refresh

        # Pure-Python cross-tab live update: app.storage.user is shared by
        # all tabs of the browser, so the account page bumps 'profile_version'
        # after a save and this per-client timer re-renders the widget when
        # it notices a new version. (Same trick the heartbeat uses for the
        # shared session state.)
        def _watch_profile() -> None:
            if app.storage.user.get('profile_version', 0) != \
                    app.storage.client.get('profile_version_seen', -1):
                app.storage.client['profile_version_seen'] = \
                    app.storage.user.get('profile_version', 0)
                if app.storage.user.get('authenticated', False):
                    account_widget.refresh()
            # Same cross-tab pattern for the application logo: the settings
            # page bumps 'logo_version' after an upload/reset.
            if app.storage.user.get('logo_version', 0) != \
                    app.storage.client.get('logo_version_seen', -1):
                app.storage.client['logo_version_seen'] = \
                    app.storage.user.get('logo_version', 0)
                logo_widget.refresh()

        ui.timer(2.0, _watch_profile)

    # Panel colour with a subtle network-circuit texture on the header,
    # and a bottom border that visually separates it from the sub pages.
    header.style(
        'background-color: var(--panel-bg);'
        "background-image: url('/assets/images/header_bg.svg');"
        'background-size: cover; background-position: center;'
        'border-bottom: 1px solid var(--border);'
    )

    # Sidebar nav
    with ui.left_drawer().classes('text-black relative').style(
        'background-color: var(--panel-bg);'
        'border-right: 1px solid var(--border);'
        'transition: width 0.3s ease-in-out;'
    ).props('breakpoint=1024') as left_drawer:

        sidebar_labels = []
        nav_links = []
        sidebar_hints = []

        with ui.link('', '/').classes('w-full no-underline text-black').style('border-radius: 2rem;') as dashboard_link:
            with ui.row().classes('items-center mb-2 mt-2 cursor-pointer w-full no-wrap'):
                dashboard_icon = ui.icon('dashboard').classes('ml-5 text-2xl flex-shrink-0')
                dashboard_label = i18n.bind(ui.label('Dashboard').classes('text-lg sidebar-label ml-3 flex-shrink-0'), 'nav.dashboard')
                sidebar_labels.append(dashboard_label)
            sidebar_hints.append(sidebar_hint('nav.dashboard'))
        nav_links.append({'link': dashboard_link, 'icon': dashboard_icon, 'patterns': ['/'], 'exact': True})

        with ui.link('', '/shipping').classes('w-full no-underline text-black').style('border-radius: 2rem;') as shipping_link:
            with ui.row().classes('items-center mb-2 mt-2 cursor-pointer w-full no-wrap'):
                shipping_icon = ui.icon('local_shipping').classes('ml-5 text-2xl flex-shrink-0')
                shipping_label = i18n.bind(ui.label('Shipping').classes('text-lg sidebar-label ml-3 flex-shrink-0'), 'nav.shipping')
                sidebar_labels.append(shipping_label)
            sidebar_hints.append(sidebar_hint('nav.shipping'))
        nav_links.append({'link': shipping_link, 'icon': shipping_icon, 'patterns': ['/shipping', '/customer'], 'exact': False})

        with ui.link('', '/production').classes('w-full no-underline text-black').style('border-radius: 2rem;') as production_link:
            with ui.row().classes('items-center mb-2 mt-2 cursor-pointer w-full no-wrap'):
                production_icon = ui.icon('precision_manufacturing').classes('ml-5 text-2xl flex-shrink-0')
                production_label = i18n.bind(ui.label('Production').classes('text-lg sidebar-label ml-3 flex-shrink-0'), 'nav.production')
                sidebar_labels.append(production_label)
            sidebar_hints.append(sidebar_hint('nav.production'))
        nav_links.append({'link': production_link, 'icon': production_icon, 'patterns': ['/production'], 'exact': False})

        with ui.link('', '/orders').classes('w-full no-underline text-black').style('border-radius: 2rem;') as orders_link:
            with ui.row().classes('items-center mb-2 mt-2 cursor-pointer w-full no-wrap'):
                orders_icon = ui.icon('fact_check').classes('ml-5 text-2xl flex-shrink-0')
                orders_label = i18n.bind(ui.label('Orders').classes('text-lg sidebar-label ml-3 flex-shrink-0'), 'nav.orders')
                sidebar_labels.append(orders_label)
            sidebar_hints.append(sidebar_hint('nav.orders'))
        nav_links.append({'link': orders_link, 'icon': orders_icon, 'patterns': ['/orders'], 'exact': False})

        with ui.link('', '/pallets').classes('w-full no-underline text-black').style('border-radius: 2rem;') as pallets_link:
            with ui.row().classes('items-center mb-2 mt-2 cursor-pointer w-full no-wrap'):
                pallets_icon = ui.icon('pallet').classes('ml-5 text-2xl flex-shrink-0')
                pallets_label = i18n.bind(ui.label('Pallets').classes('text-lg sidebar-label ml-3 flex-shrink-0'), 'nav.pallets')
                sidebar_labels.append(pallets_label)
            sidebar_hints.append(sidebar_hint('nav.pallets'))
        nav_links.append({'link': pallets_link, 'icon': pallets_icon, 'patterns': ['/pallets'], 'exact': False})

        with ui.link('', '/packing').classes('w-full no-underline text-black').style('border-radius: 2rem;') as packing_link:
            with ui.row().classes('items-center mb-2 mt-2 cursor-pointer w-full no-wrap'):
                packing_icon = ui.icon('inventory_2').classes('ml-5 text-2xl flex-shrink-0')
                packing_label = i18n.bind(ui.label('Packing').classes('text-lg sidebar-label ml-3 flex-shrink-0'), 'nav.packing')
                sidebar_labels.append(packing_label)
            sidebar_hints.append(sidebar_hint('nav.packing'))
        nav_links.append({'link': packing_link, 'icon': packing_icon, 'patterns': ['/packing'], 'exact': False})

        with ui.link('', '/print-demo').classes('w-full no-underline text-black').style('border-radius: 2rem;') as print_demo_link:
            with ui.row().classes('items-center mb-2 mt-2 cursor-pointer w-full no-wrap'):
                print_demo_icon = ui.icon('print').classes('ml-5 text-2xl flex-shrink-0')
                print_demo_label = i18n.bind(ui.label('Print Demo').classes('text-lg sidebar-label ml-3 flex-shrink-0'), 'nav.print_demo')
                sidebar_labels.append(print_demo_label)
            sidebar_hints.append(sidebar_hint('nav.print_demo'))
        nav_links.append({'link': print_demo_link, 'icon': print_demo_icon, 'patterns': ['/print-demo'], 'exact': False})


        from models.enums import UserRole as _Role
        if app.storage.user.get('role') == _Role.ADMIN.value:
            with ui.link('', '/jobs').classes('w-full no-underline text-black').style('border-radius: 2rem;') as jobs_link:
                with ui.row().classes('items-center mb-2 mt-2 cursor-pointer w-full no-wrap'):
                    jobs_icon = ui.icon('list_alt').classes('ml-5 text-2xl flex-shrink-0')
                    jobs_label = i18n.bind(ui.label('Jobs').classes('text-lg sidebar-label ml-3 flex-shrink-0'), 'nav.jobs')
                    sidebar_labels.append(jobs_label)
                sidebar_hints.append(sidebar_hint('nav.jobs'))
                nav_links.append({'link': jobs_link, 'icon': jobs_icon, 'patterns': ['/jobs'], 'exact': False})


        ui.separator()

        with ui.link('', '/icons').classes('w-full no-underline text-black').style('border-radius: 2rem;') as icons_link:
            with ui.row().classes('items-center mb-2 mt-2 cursor-pointer w-full no-wrap'):
                icons_icon = ui.icon('grid_view').classes('ml-5 text-2xl flex-shrink-0')
                icons_label = i18n.bind(ui.label('Icons').classes('text-lg sidebar-label ml-3 flex-shrink-0'), 'nav.icons')
                sidebar_labels.append(icons_label)
            sidebar_hints.append(sidebar_hint('nav.icons'))
        nav_links.append({'link': icons_link, 'icon': icons_icon, 'patterns': ['/icons'], 'exact': False})


        with ui.link('', '/design-system').classes('w-full no-underline text-black').style('border-radius: 2rem;') as design_system_link:
            with ui.row().classes('items-center mb-2 mt-2 cursor-pointer w-full no-wrap'):
                design_system_icon = ui.icon('palette').classes('ml-5 text-2xl flex-shrink-0')
                design_system_label = i18n.bind(ui.label('Design System').classes('text-lg sidebar-label ml-3 flex-shrink-0'), 'nav.design_system')
                sidebar_labels.append(design_system_label)
            sidebar_hints.append(sidebar_hint('nav.design_system'))
        nav_links.append({'link': design_system_link, 'icon': design_system_icon, 'patterns': ['/design-system'], 'exact': False})

        ui.separator()

        # App Settings hub is pinned at the BOTTOM of the nav bar (with the
        # version label), so it keeps its own dedicated spot whatever the
        # number of nav links above. Admin only — role comes from the login
        # snapshot in the shared session storage.
        from models.enums import UserRole as _RoleBottom
        with ui.column().classes('absolute bottom-2 left-0 right-4 items-stretch gap-0 px-2') as sidebar_bottom:
            if app.storage.user.get('role') == _RoleBottom.ADMIN.value:
                with ui.link('', '/settings').classes('w-full no-underline text-black').style('border-radius: 2rem;') as settings_link:
                    with ui.row().classes('items-center mb-2 mt-2 cursor-pointer w-full no-wrap'):
                        settings_icon = ui.icon('tune').classes('ml-5 text-2xl flex-shrink-0')
                        settings_label = i18n.bind(ui.label('App Settings').classes('text-lg sidebar-label ml-3 flex-shrink-0'), 'appsettings.title')
                        sidebar_labels.append(settings_label)
                    sidebar_hints.append(sidebar_hint('appsettings.title'))
                nav_links.append({'link': settings_link, 'icon': settings_icon, 'patterns': ['/settings'], 'exact': False})
            version_label = ui.label(version).classes('text-xs text-muted sidebar-label mr-2')
            sidebar_labels.append(version_label)

        def apply_highlight(active_item) -> None:
            for item in nav_links:
                item['link'].classes(remove='nav-link-active')
                item['icon'].classes(remove='nav-icon-active')
            active_item['link'].classes(add='nav-link-active')
            active_item['icon'].classes(add='nav-icon-active')

        # highlight on click without a server round-trip
        for nav_item in nav_links:
            nav_item['link'].on('click', lambda _, i=nav_item: apply_highlight(i))

        # highlight the correct item whenever the URL changes. Polling (rather
        # than only on_connect) also covers navigations that do not create a
        # new websocket, e.g. opening /settings from the header account menu.
        async def _highlight_from_path() -> None:
            try:
                path = await ui.run_javascript('window.location.pathname')
            except Exception:
                return
            for item in nav_links:
                for pattern in item['patterns']:
                    match = (path == pattern) if item['exact'] else (path == pattern or path.startswith(pattern + '/'))
                    if match:
                        apply_highlight(item)
                        return

        async def _watch_path() -> None:
            nonlocal _current_path
            try:
                path = await ui.run_javascript('window.location.pathname')
            except Exception:
                return
            if path != _current_path:
                _current_path = path
                await _highlight_from_path()

        _current_path = None
        ui.timer(1.0, _watch_path)

        # on_connect fires only for a real WebSocket, so bots never reach this
        ui.context.client.on_connect(_highlight_from_path)

    # Vertical splitter handle straddling the sidebar's right separator.
    # Rendered OUTSIDE the drawer with position:fixed, otherwise the drawer's
    # scrollable content area pushes it below the nav links. The width is
    # fully client-driven (see _SIDEBAR_SPLITTER_JS): dragging the handle
    # resizes the drawer live between 100 and 400 px, a simple click toggles
    # between icon-only (100 px) and standard (240 px), and the resulting
    # width is persisted server-side via POST /sidebar-width. The chevron
    # reflects the resulting state (wide -> collapse to the left).
    with ui.element('div').classes('sidebar-collapse-handle') as handle:
        handle_icon = ui.icon('chevron_left').classes('sidebar-collapse-handle-icon')

    # sync drawer width, labels and handle to the persisted width
    _sidebar_width = max(100, min(400, int(app.storage.user.get('sidebar-width', 240) or 240)))
    _collapsed = _sidebar_width < 180
    left_drawer.props(f'width={_sidebar_width}')
    handle.style(f'left: {_sidebar_width - 7}px;')
    handle_icon.name = 'chevron_right' if _collapsed else 'chevron_left'
    for label in sidebar_labels:
        label.classes(add='collapsed' if _collapsed else 'expanded')
    # Icon-only hints are pure CSS now: the splitter JS toggles the
    # 'sidebar-wide' class on <body> and global-css.css hides the tooltips
    # while the sidebar is wide enough to show the text labels.

    with ui.column().classes('w-full items-stretch mobile-content'):
        yield

    # About dialog
    with ui.dialog() as about_dialog, ui.card().classes('dialog-card'):
        i18n.bind(ui.label(i18n.t('about.title')).classes('dialog-title'), 'about.title')
        i18n.bind(ui.label(i18n.t('about.body')).classes('dialog-body'), 'about.body')
        with ui.element('div').classes('dialog-body'):
            i18n.bind(ui.label(i18n.t('about.source')).classes('text-sm text-muted mb-2'), 'about.source')
            i18n.bind(ui.link(i18n.t('about.repo'), 'https://github.com/frycodelab/nicegui-component-based', new_tab=True).classes('text-info').style('text-decoration: underline;'), 'about.repo')
        with ui.element('div').classes('dialog-footer'):
            i18n.bind(ui.button(i18n.t('action.close'), on_click=about_dialog.close, color='white').props('flat no-caps').classes('button button-primary button-sm'), 'action.close')

    # Mobile burger sheet with the remaining sections, hidden on desktop
    with ui.dialog().props('position=bottom') as menu_sheet, ui.card().classes('mobile-sheet'):
        ui.element('div').classes('mobile-sheet-handle')
        i18n.bind(ui.label(i18n.t('menu.all_sections')).classes('mobile-sheet-title'), 'menu.all_sections')
        with ui.element('div').classes('mobile-sheet-grid'):
            for label_key, icon_name, target in _SHEET_SECTIONS:
                with ui.element('div').classes('mobile-sheet-item').on('click', lambda _, t=target: [menu_sheet.close(), ui.navigate.to(t)]):
                    ui.icon(icon_name).classes('mobile-sheet-icon')
                    i18n.bind(ui.label(i18n.t(label_key)).classes('mobile-sheet-label'), label_key)
            with ui.element('div').classes('mobile-sheet-item').on('click', lambda: [menu_sheet.close(), about_dialog.open()]):
                ui.icon('info').classes('mobile-sheet-icon')
                i18n.bind(ui.label(i18n.t('menu.about')).classes('mobile-sheet-label'), 'menu.about')

        # Account actions, moved here from the top bar on mobile
        i18n.bind(ui.label(i18n.t('account.account')).classes('mobile-sheet-title').style('margin-top: 20px;'),
                  'account.account')
        with ui.element('div').classes('mobile-sheet-grid'):
            with ui.element('div').classes('mobile-sheet-item').on('click', lambda: [menu_sheet.close(), ui.navigate.to('/account')]):
                ui.icon('person').classes('mobile-sheet-icon')
                # Same destination as the desktop account dropdown (/account),
                # so it carries the same "Account" label, not "Settings".
                i18n.bind(ui.label(i18n.t('account.account')).classes('mobile-sheet-label'), 'account.account')
            from models.enums import UserRole
            if app.storage.user.get('role') == UserRole.ADMIN.value:
                # Single admin hub on mobile too: everything lives in /settings.
                with ui.element('div').classes('mobile-sheet-item').on('click', lambda: [menu_sheet.close(), ui.navigate.to('/settings')]):
                    ui.icon('tune').classes('mobile-sheet-icon')
                    i18n.bind(ui.label(i18n.t('appsettings.title')).classes('mobile-sheet-label'), 'appsettings.title')
            async def _mobile_logout() -> None:
                menu_sheet.close()
                await logout()

            with ui.element('div').classes('mobile-sheet-item').on('click', _mobile_logout):
                ui.icon('logout').classes('mobile-sheet-icon')
                i18n.bind(ui.label(i18n.t('account.logout')).classes('mobile-sheet-label'), 'account.logout')

    # Floating bottom navigation, shown only below the desktop breakpoint via CSS
    mobile_nav = []
    with ui.element('div').classes('mobile-nav-floating'):
        with ui.link('', '/').classes('mobile-nav-item') as m_home:
            ui.icon('dashboard').classes('mobile-nav-icon')
            i18n.bind(ui.label(i18n.t('nav.home')).classes('mobile-nav-label'), 'nav.home')
        mobile_nav.append({'el': m_home, 'nav': True, 'patterns': ['/'], 'exact': True})

        with ui.link('', '/shipping').classes('mobile-nav-item') as m_ship:
            ui.icon('local_shipping').classes('mobile-nav-icon')
            i18n.bind(ui.label(i18n.t('nav.shipping')).classes('mobile-nav-label'), 'nav.shipping')
        mobile_nav.append({'el': m_ship, 'nav': True, 'patterns': ['/shipping', '/customer'], 'exact': False})

        with ui.link('', '/production').classes('mobile-nav-item') as m_prod:
            ui.icon('precision_manufacturing').classes('mobile-nav-icon')
            i18n.bind(ui.label(i18n.t('nav.production')).classes('mobile-nav-label'), 'nav.production')
        mobile_nav.append({'el': m_prod, 'nav': True, 'patterns': ['/production'], 'exact': False})

        with ui.element('div').classes('mobile-nav-item').on('click', lambda: menu_sheet.open()) as m_menu:
            ui.icon('menu').classes('mobile-nav-icon')
            i18n.bind(ui.label(i18n.t('menu.menu')).classes('mobile-nav-label'), 'menu.menu')
        mobile_nav.append({'el': m_menu, 'nav': False,
                           'patterns': [t for _, _, t in _SHEET_SECTIONS], 'exact': False})

    def apply_mobile_highlight(active_item) -> None:
        for item in mobile_nav:
            item['el'].classes(remove='mobile-nav-active')
        active_item['el'].classes(add='mobile-nav-active')

    # highlight on tap for the real destinations; the burger only opens a sheet
    for item in mobile_nav:
        if item['nav']:
            item['el'].on('click', lambda _, i=item: apply_mobile_highlight(i))

    async def init_mobile_highlight() -> None:
        try:
            path = await ui.run_javascript('window.location.pathname')
        except Exception:
            return
        for item in mobile_nav:
            for pattern in item['patterns']:
                match = (path == pattern) if item['exact'] else (path == pattern or path.startswith(pattern + '/'))
                if match:
                    apply_mobile_highlight(item)
                    return

    ui.context.client.on_connect(init_mobile_highlight)