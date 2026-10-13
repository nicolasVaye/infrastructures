"""Identity providers page (admin): configure external OIDC sources (Keycloak).

CRUD over GET/POST/PATCH/DELETE /idps on the backend, plus a 'verify' action
that fetches the provider's discovery document. Client secrets are never
displayed after creation — the edit form only sends a new value when filled.
"""

from __future__ import annotations

from nicegui import app, ui

from components.dialogs import confirm_dialog, info_dialog
from components.notifications import notify
from core.database import get_session
from models.enums import UserRole
from services.i18n import t

_ROLE_OPTIONS = [r.value for r in UserRole]


def _is_admin() -> bool:
    return app.storage.user.get('role') == UserRole.ADMIN.value


def content() -> None:
    """Providers tab of the /settings admin hub (no page header; guard in hub)."""

    @ui.refreshable
    def idps_table() -> None:
        with get_session() as api:
            idps = api.get('/idps')

        if not idps:
            with ui.column().classes('card w-full items-center gap-2 p-8'):
                ui.icon('vpn_key_off', size='2rem').classes('text-muted')
                ui.label(t('idps.empty')).classes('text-muted')
            return

        with ui.column().classes('card w-full gap-0 p-0'):
            with ui.row().classes('w-full items-center px-4 py-3 label-text').style(
                'border-bottom: 1px solid var(--border, #e4e4e7);'
            ):
                ui.label(t('idps.col.name')).classes('flex-1')
                ui.label(t('idps.col.issuer')).style('width: 280px;')
                ui.label(t('idps.col.client_id')).style('width: 150px;')
                ui.label(t('idps.col.role')).style('width: 110px;')
                ui.label(t('idps.col.options')).style('width: 190px;')
                ui.label('').style('width: 150px;')

            for i in idps:
                with ui.row().classes('w-full items-center px-4 py-3 no-wrap').style(
                    'border-bottom: 1px solid var(--border, #f4f4f5);'
                ):
                    with ui.column().classes('flex-1 gap-0'):
                        ui.label(i['name']).classes('truncate')
                        ui.label('enabled' if i['enabled'] else 'disabled').classes(
                            'text-xs ' + ('text-positive' if i['enabled'] else 'text-muted'))

                    ui.label(i['issuer_url']).classes('text-xs text-muted truncate').style(
                        'width: 280px; font-family: monospace;')
                    ui.label(i['client_id']).classes('text-xs text-muted truncate').style(
                        'width: 150px; font-family: monospace;')
                    ui.label(i['default_role']).classes('text-xs').style('width: 110px;')

                    with ui.column().classes('gap-0').style('width: 190px;'):
                        ui.label('JIT provisioning: on' if i['auto_create_users']
                                 else 'JIT provisioning: off').classes('text-xs text-muted')

                    idp_id = i['id']
                    name = i['name']

                    async def _toggle(item: dict = i) -> None:
                        try:
                            with get_session() as api:
                                api.patch(f"/idps/{item['id']}", json={'enabled': not item['enabled']})
                        except Exception as exc:
                            await info_dialog(str(getattr(exc, 'detail', exc)), title=t('idps.not_possible'), danger=True)
                            return
                        notify(t('idps.toggle_msg').format(
                               name=item['name'],
                               state=t('idps.enable') if not item['enabled'] else t('idps.disabled')),
                               type='warning')
                        idps_table.refresh()

                    async def _verify(item: dict = i) -> None:
                        try:
                            with get_session() as api:
                                result = api.get(f"/idps/{item['id']}/verify")
                        except Exception as exc:
                            await info_dialog(str(getattr(exc, 'detail', exc)),
                                              title=t('idps.verify_fail'), danger=True)
                            return
                        await info_dialog(
                            t('idps.verify_ok').format(ep=result.get('token_endpoint')),
                            title=t('idps.reachable').format(name=item['name']))

                    async def _delete(item: dict = i) -> None:
                        confirmed = await confirm_dialog(
                            t('idps.delete_confirm').format(name=item['name']),
                            title=t('idps.delete_title'), danger=True)
                        if not confirmed:
                            return
                        try:
                            with get_session() as api:
                                api.delete(f"/idps/{item['id']}")
                        except Exception as exc:
                            await info_dialog(str(getattr(exc, 'detail', exc)), title=t('idps.not_possible'), danger=True)
                            return
                        notify(t('idps.deleted_msg').format(name=item['name']), type='warning')
                        idps_table.refresh()

                    async def _edit(item: dict = i) -> None:
                        await _edit_dialog(item)

                    with ui.row().style('width: 150px;'):
                        ui.button(icon='power_settings_new', on_click=_toggle).props('flat dense')
                        ui.button(icon='health_and_safety', on_click=_verify).props('flat dense color=info')
                        ui.button(icon='edit', on_click=_edit).props('flat dense')
                        ui.button(icon='delete', on_click=_delete).props('flat dense color=negative')

    async def _edit_dialog(item: dict) -> None:
        with ui.dialog() as dialog, ui.card().classes('dialog-card').style('min-width: 520px;'):
            ui.label(t('idps.edit_title') + f" '{item['name']}'").classes('dialog-title')

            ui.label(t('idps.f_name')).classes('field-label')
            name = ui.input(value=item['name'], placeholder='Corp Keycloak').classes('w-full')

            ui.label(t('idps.f_issuer')).classes('field-label')
            issuer = ui.input(value=item['issuer_url'],
                              placeholder='https://keycloak.example/realms/myrealm'
                              ).classes('w-full').style('font-family: monospace;')

            ui.label(t('idps.f_client_id')).classes('field-label')
            client_id = ui.input(value=item['client_id'],
                                  placeholder='infrastructures').classes('w-full').style('font-family: monospace;')

            ui.label(t('idps.f_secret_keep')).classes('field-label')
            client_secret = ui.input(password=True, password_toggle_button=True,
                                     placeholder='unchanged').classes('w-full')

            ui.label(t('idps.f_role')).classes('field-label')
            default_role = ui.select(_ROLE_OPTIONS, value=item['default_role']).classes('w-full')

            ui.element('div').classes('divider my-2')
            auto_create = ui.switch(t('idps.jit'),
                                    value=item['auto_create_users'])
            enabled = ui.switch('Enabled — show the button on the login page',
                                value=item['enabled'])

            async def _save() -> None:
                payload: dict = {}
                if name.value.strip() and name.value != item['name']:
                    payload['name'] = name.value.strip()
                if issuer.value.strip() and issuer.value != item['issuer_url']:
                    payload['issuer_url'] = issuer.value.strip()
                if client_id.value.strip() and client_id.value != item['client_id']:
                    payload['client_id'] = client_id.value.strip()
                if client_secret.value:
                    payload['client_secret'] = client_secret.value
                if default_role.value != item['default_role']:
                    payload['default_role'] = default_role.value
                if auto_create.value != item['auto_create_users']:
                    payload['auto_create_users'] = auto_create.value
                if enabled.value != item['enabled']:
                    payload['enabled'] = enabled.value
                if not payload:
                    dialog.close()
                    return
                try:
                    with get_session() as api:
                        api.patch(f"/idps/{item['id']}", json=payload)
                except Exception as exc:
                    await info_dialog(str(getattr(exc, 'detail', exc)), title=t('idps.not_possible'), danger=True)
                    return
                notify(t('idps.saved'), type='positive')
                dialog.close()
                idps_table.refresh()

            with ui.row().classes('w-full justify-end gap-2'):
                ui.button(t('idps.cancel'), on_click=dialog.close).props('flat no-caps')
                ui.button(t('idps.save'), icon='save', on_click=_save).props('no-caps')
        dialog.open()

    idps_table()

    # -- creation form --------------------------------------------------------

    async def _create() -> None:
        payload = {
            'name': f_name.value.strip(),
            'issuer_url': f_issuer.value.strip(),
            'client_id': f_client.value.strip(),
            'client_secret': f_secret.value,
            'default_role': f_role.value,
            'auto_create_users': f_jit.value,
            'enabled': True,
        }
        if not all([payload['name'], payload['issuer_url'], payload['client_id'], payload['client_secret']]):
            notify(t('idps.required'), type='warning')
            return
        try:
            with get_session() as api:
                api.post('/idps', json=payload)
        except Exception as exc:
            await info_dialog(str(getattr(exc, 'detail', exc)), title=t('idps.not_possible'), danger=True)
            return
        notify(t('idps.created_msg').format(name=payload['name']), type='positive')
        f_name.value = f_issuer.value = f_client.value = f_secret.value = ''
        f_jit.value = True
        idps_table.refresh()

    with ui.column().classes('card w-full gap-4 p-6').style('max-width: 720px;'):
        ui.label(t('idps.add_title')).classes('section-title')
        ui.label(t('idps.add_desc')).classes('text-sm text-muted')

        ui.label(t('idps.f_name')).classes('field-label')
        f_name = ui.input(placeholder='Corp Keycloak').classes('w-full')

        ui.label(t('idps.f_issuer')).classes('field-label')
        f_issuer = ui.input(placeholder='https://keycloak.example/realms/myrealm'
                            ).classes('w-full').style('font-family: monospace;')

        with ui.row().classes('w-full gap-4 no-wrap'):
            with ui.element('div').classes('w-full'):
                ui.label(t('idps.f_client_id')).classes('field-label')
                f_client = ui.input(placeholder='infrastructures').classes('w-full').style('font-family: monospace;')
            with ui.element('div').classes('w-full'):
                ui.label(t('idps.f_secret')).classes('field-label')
                f_secret = ui.input(password=True, password_toggle_button=True,
                                    placeholder='••••••••').classes('w-full')

        ui.label(t('idps.f_role')).classes('field-label')
        f_role = ui.select(_ROLE_OPTIONS, value='user').classes('w-full')
        ui.label(t('idps.tip') + '/auth/oidc/callback (frontend base URL)').classes('text-xs text-muted')

        f_jit = ui.switch(t('idps.jit'), value=True)
        ui.button(t('idps.add'), icon='add', on_click=_create).classes('button button-primary')
