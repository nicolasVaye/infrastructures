"""FastAPI application entry point.

Run (dev):  uvicorn app.main:app --reload --port 8000
Run (prod): uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
Workers:   python -m app.worker   (scale horizontally, any number of processes)
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.bootstrap import ensure_schema
from app.core.config import get_settings
from app.core.db import get_engine, get_session_factory

logger = logging.getLogger(__name__)

# Root logging setup, mirroring app/worker/__init__.py: without it uvicorn
# only configures its own loggers (access/error) and every application-level
# INFO record — including the SSE observability of app/events.py
# ("Listening on Postgres channel", "SSE subscriber #N connected",
# "SSE keepalive #N sent", "SSE event seq=N fanned out") — is dropped by the
# default WARNING root level, leaving the diagnostics protocol blind.
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await ensure_schema()
    # Real-time bridge: LISTEN on the Postgres events channel and fan out
    # to the SSE subscribers of GET /events.
    from app import events
    events.start_listener()
    yield
    await events.stop_listener()
    await get_engine().dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        # No custom response class: modern FastAPI serializes directly to JSON
        # bytes via Pydantic when a return type/response_model is set — faster
        # than ORJSONResponse and without the deprecation warning.
        lifespan=lifespan,
    )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    from app.api import audit, auth, idps, jobs, sessions, settings, users
    from app.api import activity
    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(sessions.router)
    app.include_router(audit.router)
    app.include_router(jobs.router)
    app.include_router(idps.router)
    app.include_router(settings.router)
    app.include_router(activity.router)

    # Real-time change events (SSE) — see app/events.py
    from app import events
    from fastapi import Depends
    app.get("/events", tags=["events"])(events.events)

    @app.get("/health", tags=["meta"])
    async def health() -> dict:
        """Liveness + database readiness probe.

        A static 200 here used to report a healthy process while every query
        failed (Postgres restarting, network partition) — orchestrators
        (compose healthcheck, Swarm, k8s) must be able to see the difference.
        """
        from fastapi.responses import JSONResponse
        from sqlalchemy import text
        try:
            async with get_session_factory()() as session:
                await session.execute(text("SELECT 1"))
        except Exception:  # noqa: BLE001 — any DB failure = unhealthy
            return JSONResponse({"status": "degraded", "database": "unreachable"},
                                status_code=503)
        return {"status": "ok", "database": "ok"}

    return app


app = create_app()
