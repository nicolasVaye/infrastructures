"""Shared pytest fixtures.

Enables the NiceGUI testing plugin. The frontend is now a pure REST client of
the backend, so there is no local database to isolate anymore; service-layer
tests use a fake API session instead of HTTP calls.
"""

import pytest

# user_plugin provides the user-simulation fixtures without the full Selenium stack.
pytest_plugins = ['nicegui.testing.user_plugin']


class FakeApiSession:
    """Minimal stand-in for core.database.ApiSession used in service tests."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []

    def _record(self, method: str, path: str, **kwargs):
        self.calls.append((method, path, kwargs.get('json')))
        return {}

    def get(self, path, **kwargs):
        self.calls.append(('GET', path, kwargs.get('params')))
        return kwargs.get('returns', [])
    def post(self, path, **kwargs):
        return self._record('POST', path, **kwargs)
    def put(self, path, **kwargs):
        return self._record('PUT', path, **kwargs)
    def patch(self, path, **kwargs):
        return self._record('PATCH', path, **kwargs)
    def delete(self, path, **kwargs):
        self._record('DELETE', path, **kwargs)
        return None


@pytest.fixture
def fake_api_session() -> FakeApiSession:
    return FakeApiSession()
