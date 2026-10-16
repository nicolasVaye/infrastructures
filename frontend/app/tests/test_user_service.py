"""Service-layer tests using a fake API session (no HTTP, no backend needed)."""

from shared.enums import UserRole

from services.user_service import UserService


def test_create_user_payload(fake_api_session):
    service = UserService(fake_api_session)
    _, initial_password = service.create_user('alice', role=UserRole.OPERATOR)
    method, path, payload = fake_api_session.calls[-1]
    assert method == 'POST'
    assert path == '/users'
    assert payload['username'] == 'alice'
    assert payload['role'] == 'operator'
    # The password is generated server-side (random, one-time): the create
    # payload must NOT carry any password, and the one-time value is
    # returned to the caller for display.
    assert 'password' not in payload
    assert initial_password is None or isinstance(initial_password, str)


def test_create_user_empty_username_raises(fake_api_session):
    service = UserService(fake_api_session)
    try:
        service.create_user('   ')
        raise AssertionError('expected ValueError')
    except ValueError as exc:
        assert 'required' in str(exc)


def test_delete_user(fake_api_session):
    service = UserService(fake_api_session)
    service.delete_user(42)
    method, path, _ = fake_api_session.calls[-1]
    assert method == 'DELETE'
    assert path == '/users/42'
