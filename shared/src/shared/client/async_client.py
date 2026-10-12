"""Async REST client for the infrastructures backend.

Used by external automations, scheduled scripts and any async service that
needs to authenticate (JWT), submit jobs and follow them:

    from shared.client import AsyncClient

    async with AsyncClient("http://backend:8000") as client:
        await client.login("robot", "secret")
        job = await client.submit_job("demo.sleep", {"seconds": 2})
        job = await client.wait_for_job(job.id)
"""

from __future__ import annotations

import asyncio
from types import TracebackType
from typing import Any

import httpx

from shared.enums import AuditAction, JobStatus
from shared.models import (
    AuditOut,
    JobCreate,
    JobOut,
    LoginRequest,
    SessionOut,
    TokenPair,
    UserOut,
)


class ApiError(RuntimeError):
    """Raised when the backend answers with a 4xx/5xx response."""

    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"API error {status_code}: {detail}")


class AsyncClient:
    """Async httpx client with JWT handling and automatic token refresh."""

    def __init__(self, base_url: str, *, timeout: float = 30.0) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip('/'),
            timeout=timeout,
            headers={"Accept": "application/json"},
        )
        self._access_token: str | None = None
        self._refresh_token: str | None = None

    async def __aenter__(self) -> "AsyncClient":
        return self

    async def __aexit__(self, *_: TracebackType | None) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    # -- low-level ---------------------------------------------------------

    async def _request(
        self, method: str, path: str, *, auth: bool = True, **kwargs: Any
    ) -> Any:
        headers = kwargs.pop("headers", {})
        if auth and self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        response = await self._http.request(method, path, headers=headers, **kwargs)
        if response.status_code == 401 and auth and self._refresh_token:
            if await self._refresh():
                headers["Authorization"] = f"Bearer {self._access_token}"
                response = await self._http.request(method, path, headers=headers, **kwargs)
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except Exception:
                detail = response.text
            raise ApiError(response.status_code, detail)
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    async def _refresh(self) -> bool:
        response = await self._http.post(
            "/auth/refresh", json={"refresh_token": self._refresh_token}
        )
        if response.status_code != 200:
            return False
        data = response.json()
        self._access_token = data["access_token"]
        self._refresh_token = data["refresh_token"]
        return True

    # -- auth -------------------------------------------------------------

    async def login(self, username: str, password: str, *, client_label: str = "automation") -> UserOut:
        """Authenticate and keep the JWT pair for subsequent calls."""
        data = await self._request(
            "POST", "/auth/login", auth=False,
            json=LoginRequest(username=username, password=password).model_dump(),
            headers={"X-Client-Label": client_label},
        )
        pair = TokenPair.model_validate(data)
        self._access_token = pair.access_token
        self._refresh_token = pair.refresh_token
        return UserOut.model_validate(await self._request("GET", "/auth/me"))

    async def logout(self) -> None:
        await self._request("POST", "/auth/logout")
        self._access_token = self._refresh_token = None

    # -- users / sessions ---------------------------------------------------

    async def me(self) -> UserOut:
        return UserOut.model_validate(await self._request("GET", "/auth/me"))

    async def users(self) -> list[UserOut]:
        return [UserOut.model_validate(u) for u in await self._request("GET", "/users")]

    async def sessions(self) -> list[SessionOut]:
        return [SessionOut.model_validate(s) for s in await self._request("GET", "/sessions")]

    async def heartbeat(self, client_label: str = "automation") -> None:
        await self._request("PUT", "/auth/heartbeat", json={"client": client_label})

    # -- jobs ---------------------------------------------------------------

    async def submit_job(self, job_type: str, params: dict[str, Any] | None = None, **extra: Any) -> JobOut:
        payload = JobCreate(job_type=job_type, params=params or {}, **extra)
        return JobOut.model_validate(
            await self._request("POST", "/jobs", json=payload.model_dump())
        )

    async def job(self, job_id: int) -> JobOut:
        return JobOut.model_validate(await self._request("GET", f"/jobs/{job_id}"))

    async def jobs(self, **params: Any) -> list[JobOut]:
        return [JobOut.model_validate(j) for j in await self._request("GET", "/jobs", params=params)]

    async def cancel_job(self, job_id: int) -> JobOut:
        return JobOut.model_validate(await self._request("POST", f"/jobs/{job_id}/cancel"))

    async def wait_for_job(
        self, job_id: int, *, poll_interval: float = 1.0, timeout: float = 300.0
    ) -> JobOut:
        """Poll a job until it reaches a terminal status."""
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            job = await self.job(job_id)
            if job.status not in (JobStatus.QUEUED, JobStatus.RUNNING):
                return job
            if asyncio.get_event_loop().time() > deadline:
                raise TimeoutError(f"Job {job_id} still pending after {timeout}s")
            await asyncio.sleep(poll_interval)

    # -- audit ---------------------------------------------------------------

    async def audit(self, limit: int = 100, **params: Any) -> list[AuditOut]:
        params["limit"] = limit
        return [AuditOut.model_validate(a) for a in await self._request("GET", "/audit", params=params)]

    async def audit_actions(self) -> list[str]:
        return [a.value for a in AuditAction]
