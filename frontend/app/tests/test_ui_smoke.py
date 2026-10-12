"""Example UI smoke tests using NiceGUI's user-simulation harness.

The full login flow now requires the backend API; these smoke tests only
verify that pages render. Wire them against a running backend
(BACKEND_URL) to test the complete journey.
"""

import pytest

pytest.importorskip('nicegui.testing')

from nicegui.testing import User


async def test_app_requires_login(user: User) -> None:
    await user.open('/')
    await user.should_see('Infrastructure Login')


async def test_login_page_renders(user: User) -> None:
    await user.open('/login')
    await user.should_see('Sign in')
