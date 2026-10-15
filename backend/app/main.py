"""FastAPI application entry point.

Run (dev):  uvicorn app.main:app --reload --port 8000
Run (prod): uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
Workers:   python -m app.worker   (scale horizontally, any number of processes)
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.bootstrap import ensure_schema
from app.core.config import get_settings
from app.core.db import get_engine

logger = logging.getLogger(__name__)


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
        return {"status": "ok"}

    return app


app = create_app()
