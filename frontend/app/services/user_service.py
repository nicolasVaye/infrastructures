"""User service — same contract as the template, but backed by the REST API.

The view layer calls :class:`UserService` exactly like before
(``UserService(session).get_all_users()``); every call is now an HTTP request
to the backend carrying the logged-in user's JWT.
"""

from __future__ import annotations

import re
import string
from datetime import datetime

from shared.client.async_client import ApiError
from shared.enums import UserRole

from models.user import User

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _is_valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(email))


DEFAULT_USER_PASSWORD = 'changeme'

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 64


def password_requirements(password: str) -> list[tuple[str, bool]]:
    return [
        ('password.req.length',  MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH),
        ('password.req.upper',   any(c.isupper() for c in password)),
        ('password.req.lower',   any(c.islower() for c in password)),
        ('password.req.number',  any(c.isdigit() for c in password)),
        ('password.req.special', any(c in string.punctuation for c in password)),
    ]


_REQUIREMENT_LABELS = {
    'password.req.length':  f'{MIN_PASSWORD_LENGTH}\u2013{MAX_PASSWORD_LENGTH} characters',
    'password.req.upper':   'At least one uppercase letter',
    'password.req.lower':    'At least one lowercase letter',
    'password.req.number':   'At least one number',
    'password.req.special': 'At least one special character',
}


def validate_password(password: str) -> None:
    """Raise ``ValueError`` when the password violates the policy."""
    unmet = [_REQUIREMENT_LABELS[key] for key, ok in password_requirements(password) if not ok]
    if unmet:
        raise ValueError('Password requirements not met: ' + '; '.join(unmet) + '.')


_PROTECTED_USERNAME = 'admin'


def _json_to_user(data: dict) -> User:
    """Convert a backend UserOut JSON payload into the domain dataclass."""
    return User(
        id=data['id'],
        username=data['username'],
        role=UserRole(data['role']),
        auth_provider=data.get('auth_provider', 'local'),
        idp_name=data.get('idp_name'),
        is_active=data['is_active'],
        must_change_password=data['must_change_password'],
        created_at=str(data.get('created_at', '')),
        email=data.get('email'),
        display_name=data.get('display_name'),
        avatar=data.get('avatar'),
        language=data.get('language', 'en'),
    )


class UserService:
    def __init__(self, session) -> None:
        self.session = session  # core.database.ApiSession

    # Queries
    def get_all_users(self) -> list[User]:
        users = self.session.get('/users')
        return [_json_to_user(u) for u in users]

    def get_user(self, user_id: int) -> User | None:
        try:
            return _json_to_user(self.session.get(f'/users/{user_id}'))
        except ApiError as exc:
            if exc.status_code == 404:
                return None
            raise

    def get_user_by_username(self, username: str) -> User | None:
        for user in self.get_all_users():
            if user.username == username:
                return user
        return None

    def count_admins(self) -> int:
        return sum(1 for u in self.get_all_users() if u.is_admin and u.is_active)

    # Authentication
    def verify_credentials(self, username: str, password: str) -> User | None:
        """Not used anymore: authentication happens on the backend.

        Kept for API compatibility; the login view calls the backend directly
        via :class:`services.api_client` so JWTs are never exposed here.
        """
        return None

    # Mutations
    def create_user(
        self,
        username: str,
        *,
        role: UserRole = UserRole.USER,
        password: str | None = None,
        must_change_password: bool = True,
    ) -> User:
        username = username.strip()
        if not username:
            raise ValueError('Username is required.')
        if password is None:
            password = DEFAULT_USER_PASSWORD
        payload = {
            'username': username,
            'password': password,
            'role': role.value,
            'must_change_password': must_change_password,
        }
        try:
            data = self.session.post('/users', json=payload)
        except ApiError as exc:
            # Surface backend validation as ValueError like the template did
            raise ValueError(str(exc.detail)) from exc
        return _json_to_user(data)

    def set_role(self, user_id: int, role: UserRole) -> None:
        try:
            self.session.patch(f'/users/{user_id}', json={'role': role.value})
        except ApiError as exc:
            raise ValueError(str(exc.detail)) from exc

    def set_active(self, user_id: int, active: bool) -> None:
        try:
            self.session.patch(f'/users/{user_id}', json={'is_active': active})
        except ApiError as exc:
            raise ValueError(str(exc.detail)) from exc

    def reset_password(self, user_id: int) -> None:
        try:
            self.session.post(f'/users/{user_id}/reset-password')
        except ApiError as exc:
            raise ValueError(str(exc.detail)) from exc

    def change_password(self, user_id: int, new_password: str) -> None:
        validate_password(new_password)
        try:
            self.session.put('/me/password', json={'new_password': new_password})
        except ApiError as exc:
            raise ValueError(str(exc.detail)) from exc

    def update_profile(self, user_id: int, *, email: str | None,
                       display_name: str | None,
                       avatar: str | None = None) -> dict | None:
        """Update the caller's profile.

        ``avatar`` semantics: None = leave untouched, '' = clear the avatar,
        any other string = new avatar data URL. Same for email/display_name:
        explicitly sent empty strings clear the field.
        """
        email = (email or '').strip()
        display_name = (display_name or '').strip()
        if email and not _is_valid_email(email):
            raise ValueError('Please enter a valid email address.')
        payload = {'email': email, 'display_name': display_name}
        if avatar is not None:
            payload['avatar'] = avatar
        try:
            return self.session.patch('/me/profile', json=payload)
        except ApiError as exc:
            raise ValueError(str(exc.detail)) from exc

    def set_avatar(self, user_id: int, avatar: str | None) -> None:
        self.session.patch('/me/profile', json={'avatar': avatar})

    def set_language(self, user_id: int, language: str) -> None:
        self.session.patch('/me/profile', json={'language': language})

    def set_theme(self, user_id: int, theme: str) -> None:
        self.session.patch('/me/profile', json={'theme': theme})

    def delete_user(self, user_id: int) -> None:
        try:
            self.session.delete(f'/users/{user_id}')
        except ApiError as exc:
            raise ValueError(str(exc.detail)) from exc
