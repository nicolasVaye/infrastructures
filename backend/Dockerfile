FROM python:3.12-slim

WORKDIR /srv

# Install uv for fast dependency resolution, then the shared package and backend
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY shared/ /srv/shared/
# uv.lock is the committed lockfile: with it present, `uv sync` installs the
# exact same dependency tree on every build (see `make lock` / README).
COPY backend/pyproject.toml backend/uv.lock* /srv/backend/

WORKDIR /srv/backend
RUN uv sync --no-dev --no-install-project

COPY backend/ /srv/backend/
RUN uv sync --no-dev

EXPOSE 8000

# Stateless API server — scale horizontally behind a load balancer.
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
