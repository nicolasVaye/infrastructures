"""Alembic environment: async engine, driven programmatically or via CLI.

Runs with the application's DATABASE_URL (pydantic settings, async driver
kept as-is: +asyncpg / +aiosqlite — async_engine_from_config needs an async
dialect). The API and workers call ``command.upgrade(cfg, "head")`` from
app.bootstrap on startup, inside a worker thread (env.py owns its event
loop there); ``alembic revision`` autogeneration works from the CLI with a
standalone engine.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import get_settings
from app.core.db import Base

# Import every module that registers tables on the metadata.
from app.core import db as _db  # noqa: F401,F403  (all records)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    section = config.get_section(config.config_ini_section) or {}
    engine = async_engine_from_config(section, prefix="sqlalchemy.",
                                      poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
