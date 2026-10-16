"""Runtime configuration, loaded from environment variables (12-factor)."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    # App
    app_name: str = "Infrastructures API"
    debug: bool = False
    api_prefix: str = ""
    cors_origins: list[str] = ["http://localhost:8080"]

    # Database — Postgres in production, SQLite fallback for local dev.
    # e.g. postgresql+asyncpg://infra:infra@localhost:5432/infrastructures
    database_url: str = "sqlite+aiosqlite:///./infrastructures.db"

    # Auth
    jwt_secret: str = "CHANGE_ME_IN_PRODUCTION"
    access_token_ttl_seconds: int = 30 * 60        # 30 min
    refresh_token_ttl_seconds: int = 12 * 60 * 60  # 12 h
    heartbeat_ttl_seconds: int = 180               # a session is "connected" for 3 min after its last heartbeat

    # Seed admin (first run only, must change password on first login)
    seed_admin_username: str = "admin"
    seed_admin_password: str = "admin"

    # Reverse proxies allowed to set a trustworthy X-Forwarded-For (CIDRs).
    # Requests from outside these ranges are keyed by their TCP peer IP for
    # rate limiting — a spoofed XFF then cannot rotate the limiter's key.
    # Default trusts the private docker/overlay networks only.
    trusted_proxies: list[str] = [
        "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8",
    ]

    # OIDC / external identity providers
    # Public base URL of the frontend as seen from the user's browser; the
    # OIDC redirect_uri is built from it: {base}/auth/oidc/callback
    oidc_redirect_base_url: str = "http://localhost:8080"
    oidc_state_ttl_seconds: int = 300

    # Workers
    worker_poll_interval: float = 1.0
    worker_batch_size: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()
