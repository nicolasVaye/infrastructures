"""Synchronous REST client — thin wrapper around :class:`AsyncClient` helpers.

The NiceGUI template views call services synchronously; this facade keeps that
contract while speaking HTTP to the backend. It is deliberately small: heavy
polling or high-volume automations should use :class:`AsyncClient` instead.
"""

from __future__ import annotations

import httpx

from shared.client.async_client import ApiError


class SyncClient:
    """Synchronous httpx client with JWT handling and automatic refresh."""

    def __init__(self, base_url: str, *, timeout: float = 30.0) -> None:
        self._http = httpx.Client(
            base_url=base_url.rstrip('/'),
            timeout=timeout,
            headers={"Accept": "application/json"},
        )
        self._access_token: str | None = None
        self._refresh_token: str | None = None

    def close(self) -> None:
        self._http.close()

    def set_tokens(self, access_token: str, refresh_token: str) -> None:
        """Restore tokens previously stored (e.g. in NiceGUI storage)."""
        self._access_token = access_token
        self._refresh_token = refresh_token

    @property
    def authenticated(self) -> bool:
        return self._access_token is not None

    def request(self, method: str, path: str, *, auth: bool = True, **kwargs) -> dict | list | None:
        headers = kwargs.pop("headers", {})
        if auth and self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        response = self._http.request(method, path, headers=headers, **kwargs)
        if response.status_code == 401 and auth and self._refresh_token and self._refresh():
            headers["Authorization"] = f"Bearer {self._access_token}"
            response = self._http.request(method, path, headers=headers, **kwargs)
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except Exception:
                detail = response.text
            raise ApiError(response.status_code, detail)
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def get(self, path: str, **kwargs):
        return self.request("GET", path, **kwargs)

    def get_raw(self, path: str, **kwargs) -> httpx.Response:
        """GET returning the raw response (binary payloads: avatars, logos).

        Same auth/refresh handling as :meth:`request`, but the body is NOT
        JSON-decoded — image bytes must survive intact.
        """
        headers = kwargs.pop("headers", {})
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        response = self._http.request("GET", path, headers=headers, **kwargs)
        if response.status_code == 401 and self._refresh_token and self._refresh():
            headers["Authorization"] = f"Bearer {self._access_token}"
            response = self._http.request("GET", path, headers=headers, **kwargs)
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except Exception:
                detail = response.text
            raise ApiError(response.status_code, detail)
        return response

    def post(self, path: str, **kwargs):
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs):
        return self.request("PUT", path, **kwargs)

    def patch(self, path: str, **kwargs):
        return self.request("PATCH", path, **kwargs)

    def delete(self, path: str, **kwargs):
        return self.request("DELETE", path, **kwargs)

    # -- auth ---------------------------------------------------------------

    def login(self, username: str, password: str, *, client_label: str = "web") -> dict:
        data = self.request(
            "POST", "/auth/login", auth=False,
            json={"username": username, "password": password},
            headers={"X-Client-Label": client_label},
        )
        self._access_token = data["access_token"]
        self._refresh_token = data["refresh_token"]
        return data

    def refresh(self) -> bool:
        return self._refresh()

    def _refresh(self) -> bool:
        if not self._refresh_token:
            return False
        response = self._http.post("/auth/refresh", json={"refresh_token": self._refresh_token})
        if response.status_code != 200:
            return False
        self._access_token = response.json()["access_token"]
        self._refresh_token = response.json()["refresh_token"]
        return True

    def logout(self) -> None:
        try:
            self.request("POST", "/auth/logout")
        finally:
            self._access_token = self._refresh_token = None
