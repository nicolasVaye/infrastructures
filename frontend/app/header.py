"""Application shell: header bar, collapsible sidebar and active-link tracking."""

from contextlib import contextmanager
import asyncio
from components.notifications import notify, notify_ongoing
from components.sidebar_hint import sidebar_hint
from nicegui import ui, app
from core.security import logout, current_user
from services import i18n


# Sections surfaced through the mobile burger sheet, beyond the primary tabs
# of the floating bar (Home, Examples). The sheet mirrors the nav-bar, so it
# carries the same role gating as the desktop sidebar (Jobs = admin only).
def _sheet_sections() -> list:
    from models.enums import UserRole
    sections = [('nav.examples', 'category', '/examples')]
    if app.storage.user.get('role') == UserRole.ADMIN.value:
        sections.append(('nav.jobs', 'list_alt', '/jobs'))
    return sections


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

        def add_nav_item(target: str, icon_name: str, label_key: str,
                         patterns: list, exact: bool = False) -> None:
            """One sidebar entry: link + icon + collapsible label + hover hint.

            The created element attaches to whatever container is current when
            the function is called (NiceGUI's element stack is dynamic, not
            lexical), and the highlight data is appended to nav_links so both
            the click handler and the path watcher can highlight the item.
            """
            with ui.link('', target).classes('w-full no-underline text-black').style('border-radius: 2rem;') as link:
                with ui.row().classes('items-center mb-2 mt-2 cursor-pointer w-full no-wrap'):
                    icon = ui.icon(icon_name).classes('ml-5 text-2xl flex-shrink-0')
                    label = i18n.bind(ui.label(label_key.split('.')[-1].title()).classes('text-lg sidebar-label ml-3 flex-shrink-0'), label_key)
                    sidebar_labels.append(label)
                # Inside the link scope: the tooltip attaches to the link.
                sidebar_hint(label_key)
            nav_links.append({'link': link, 'icon': icon, 'patterns': patterns, 'exact': exact})

        def add_nav_branch(target: str, icon_name: str, label_key: str,
                           children: list) -> None:
            """Expandable nav entry: treeview branches below the parent link.

            Clicking the parent navigates AND toggles the branch container
            (the whole entry is the toggle target — no separate expander
            handle to click precisely). Children register their own
            highlight entry; the parent matches its path exactly so a child
            page highlights the child, not the parent.
            """
            with ui.link('', target).classes('w-full no-underline text-black').style('border-radius: 2rem;') as link:
                with ui.row().classes('items-center mb-2 mt-2 cursor-pointer w-full no-wrap'):
                    icon = ui.icon(icon_name).classes('ml-5 text-2xl flex-shrink-0')
                    label = i18n.bind(ui.label(label_key.split('.')[-1].title()).classes('text-lg sidebar-label ml-3 flex-shrink-0'), label_key)
                    sidebar_labels.append(label)
                    # Chevron state is carried by the ICON NAME, not by a CSS
                    # rotation: the swapped glyph is identical on every
                    # browser (a rotated chevron rendered inconsistently in
                    # Firefox) and always matches the branch visibility.
                    chevron = ui.icon('chevron_right') \
                        .classes('sidebar-nav-branch-chevron ml-auto text-lg text-muted flex-shrink-0') \
                        .style('margin-right: 1.25rem;')
                sidebar_hint(label_key)
            nav_links.append({'link': link, 'icon': icon, 'patterns': [target], 'exact': True})

            def _toggle() -> None:
                if 'closed' in branch_box.classes:
                    branch_box.classes(remove='closed')
                    chevron.name = 'expand_more'
                else:
                    branch_box.classes(add='closed')
                    chevron.name = 'chevron_right'

            link.on('click', lambda _: _toggle())

            with ui.element('div').classes('sidebar-nav-children closed') as branch_box:
                for child_key, child_target in children:
                    with ui.link('', child_target).classes('w-full no-underline text-black').style('border-radius: 2rem;') as clink:
                        with ui.row().classes('items-center mb-1 mt-1 cursor-pointer w-full no-wrap'):
                            # Treeview leaf: a small muted bullet, not a heavy
                            # arrow glyph (the arrow_right triangle read as a
                            # play button next to every branch).
                            cicon = ui.icon('fiber_manual_record', size='0.5rem') \
                                .classes('text-muted flex-shrink-0') \
                                .style('width: 22px; display: inline-flex; justify-content: center;')
                            clabel = i18n.bind(ui.label(child_key.split('.')[-1].title()).classes('sidebar-label ml-1 flex-shrink-0'), child_key)
                            sidebar_labels.append(clabel)
                    nav_links.append({'link': clink, 'icon': cicon, 'patterns': [child_target], 'exact': True})

        # Whole-drawer scroll wrapper (fills the drawer height): the
        # scrollbar runs the full nav-bar and the sticky bottom hub stays
        # pinned over it (see .sidebar-nav-scroll / .sidebar-bottom CSS).
        with ui.element('div').classes('sidebar-nav-scroll'):
            add_nav_item('/', 'dashboard', 'nav.dashboard', ['/'], exact=True)
            # Examples hub: every demo section lives in ONE sub-page with a
            # tab per former top-level page, so the nav bar stays short. The
            # item also highlights on the legacy paths (deep links still work).
            add_nav_item('/examples', 'category', 'nav.examples',
                         ['/examples', '/shipping', '/customer', '/production',
                          '/orders', '/pallets', '/packing', '/print-demo',
                          '/icons', '/design-system'])
            from models.enums import UserRole as _Role
            if app.storage.user.get('role') == _Role.ADMIN.value:
                add_nav_item('/jobs', 'list_alt', 'nav.jobs', ['/jobs'])
            # TEMPORARY: 8 dummy links (blank sub-pages) to stress-test the
            # sidebar scrolling on short viewports. Remove together with
            # views/demo_content.py and the /demo-* routes in main.py.
            # Demo 3 carries expandable sub-links (treeview branches) — a UX
            # probe for grouping nav entries under a parent.
            for _i in range(1, 9):
                if _i == 3:
                    add_nav_branch(f'/demo-{_i}', 'science', f'nav.demo_{_i}',
                                   [(f'nav.demo_{_i}_{_b}', f'/demo-{_i}/{_b}')
                                    for _b in (1, 2, 3)])
                else:
                    add_nav_item(f'/demo-{_i}', 'science', f'nav.demo_{_i}', [f'/demo-{_i}'])

            # App Settings hub is pinned at the BOTTOM of the nav bar (with
            # the version label). It lives INSIDE the scrolling wrapper but
            # is position: sticky (see .sidebar-bottom CSS): the scrollbar
            # spans the full nav-bar and the hub always stays visible,
            # without ever overlapping the links. Admin only — role comes
            # from the login snapshot in the shared session storage.
            from models.enums import UserRole as _RoleBottom
            with ui.column().classes('sidebar-bottom w-full items-stretch gap-0 px-2 pb-2') as sidebar_bottom:
                if app.storage.user.get('role') == _RoleBottom.ADMIN.value:
                    with ui.link('', '/settings').classes('w-full no-underline text-black').style('border-radius: 2rem;') as settings_link:
                        with ui.row().classes('items-center mb-2 mt-2 cursor-pointer w-full no-wrap'):
                            settings_icon = ui.icon('tune').classes('ml-5 text-2xl flex-shrink-0')
                            settings_label = i18n.bind(ui.label('App Settings').classes('text-lg sidebar-label ml-3 flex-shrink-0'), 'appsettings.title')
                            sidebar_labels.append(settings_label)
                        sidebar_hint('appsettings.title')
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
                # Activity profiling for the Users-tab sparkline: one tiny
                # POST per navigation, never awaited (fire-and-forget task)
                # so the highlight never waits on the backend.
                from services import api_client
                asyncio.create_task(api_client.track_activity(path))

        _current_path = None
        ui.timer(1.0, _watch_path)

        # on_connect fires only for a real WebSocket, so bots never reach this
        ui.context.client.on_connect(_highlight_from_path)

        # Vertical splitter handle straddling the sidebar's right separator.
        # It lives INSIDE the drawer and is anchored to its right edge by CSS
        # (position: absolute; right: -5px in global-css.css, with the drawer
        # itself as containing block — absolutely positioned elements whose
        # containing block is outside the scroll area neither scroll with the
        # links nor get clipped by them). Its position is therefore a
        # CONSEQUENCE of the layout: every width phase — drag, click-toggle
        # animation, Quasar restoring the model width after a tablet
        # round-trip — moves it for free, with zero JavaScript bookkeeping.
        # The old position:fixed copy rendered outside the drawer and needed
        # its 'left' re-synced from JS on every such phase; each missed phase
        # left the handle detached from the nav-bar edge.
        with ui.element('div').classes('sidebar-collapse-handle') as handle:
            handle_icon = ui.icon('chevron_left').classes('sidebar-collapse-handle-icon')

    # sync drawer width and labels to the persisted width
    _sidebar_width = max(100, min(400, int(app.storage.user.get('sidebar-width', 240) or 240)))
    _collapsed = _sidebar_width < 180
    left_drawer.props(f'width={_sidebar_width}')
    handle_icon.name = 'chevron_right' if _collapsed else 'chevron_left'
    for label in sidebar_labels:
        label.classes(add='collapsed' if _collapsed else 'expanded')
    # Icon-only hints are pure CSS now: the splitter JS toggles the
    # 'sidebar-wide' class on <body> and global-css.css hides the tooltips
    # while the sidebar is wide enough to show the text labels.

    with ui.column().classes('w-full items-stretch mobile-content'):
        yield

    # Mobile burger sheet with the remaining sections, hidden on desktop
    sheet_sections = _sheet_sections()
    with ui.dialog().props('position=bottom') as menu_sheet, ui.card().classes('mobile-sheet'):
        ui.element('div').classes('mobile-sheet-handle')
        i18n.bind(ui.label(i18n.t('menu.all_sections')).classes('mobile-sheet-title'), 'menu.all_sections')
        with ui.element('div').classes('mobile-sheet-grid'):
            for label_key, icon_name, target in sheet_sections:
                with ui.element('div').classes('mobile-sheet-item').on('click', lambda _, t=target: [menu_sheet.close(), ui.navigate.to(t)]):
                    ui.icon(icon_name).classes('mobile-sheet-icon')
                    i18n.bind(ui.label(i18n.t(label_key)).classes('mobile-sheet-label'), label_key)

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

        with ui.link('', '/examples').classes('mobile-nav-item') as m_examples:
            ui.icon('category').classes('mobile-nav-icon')
            i18n.bind(ui.label(i18n.t('nav.examples')).classes('mobile-nav-label'), 'nav.examples')
        mobile_nav.append({'el': m_examples, 'nav': True,
                           'patterns': ['/examples', '/shipping', '/customer', '/production',
                                        '/orders', '/pallets', '/packing', '/print-demo',
                                        '/icons', '/design-system'], 'exact': False})

        with ui.element('div').classes('mobile-nav-item').on('click', lambda: menu_sheet.open()) as m_menu:
            ui.icon('menu').classes('mobile-nav-icon')
            i18n.bind(ui.label(i18n.t('menu.menu')).classes('mobile-nav-label'), 'menu.menu')
        mobile_nav.append({'el': m_menu, 'nav': False,
                           'patterns': [t for _, _, t in sheet_sections], 'exact': False})

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