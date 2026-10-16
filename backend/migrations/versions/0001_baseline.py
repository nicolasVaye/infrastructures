"""Baseline schema: the full database shape as of v7.46.

Converts the legacy ``Base.metadata.create_all`` + ad-hoc "ALTER TABLE IF NOT
EXISTS" bootstrap into a versioned migration. Existing databases are stamped
by Alembic on first startup (see app.bootstrap); fresh ones are created by
this revision. Every future schema change must be a new revision here.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-10-16
"""
from __future__ import annotations

from alembic import op

from app.core.db import Base
import app.core.db  # noqa: F401  registers all records on the metadata

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Pragmatic baseline: create the current metadata. This is equivalent to
    # the old create_all, but recorded as a revision — from here on, every
    # change is a reviewable, revertible diff instead of ad-hoc DDL.
    # SQLite has no CREATE SEQUENCE; the SSE sequence is created separately
    # by the bootstrap on Postgres only.
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
