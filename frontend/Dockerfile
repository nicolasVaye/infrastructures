# Frontend: NiceGUI app — pure REST client of the backend (stateless).
# Same layout as the backend: python:3.12-slim + uv, so every dependency
# (including NiceGUI) comes from frontend/pyproject.toml + frontend/uv.lock
# instead of floating with the zauberzeug/nicegui base image.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Shared package (DTOs + API clients) + lockfile-anchored dependency install.
# uv.lock is the committed lockfile: with it present, `uv sync` installs the
# exact same dependency tree on every build (see `make lock` / README).
COPY shared/ /srv/shared/
COPY frontend/pyproject.toml frontend/uv.lock* /srv/frontend/

WORKDIR /srv/frontend
RUN uv sync --no-dev --no-install-project

COPY frontend/app/ /srv/frontend/app/

EXPOSE 8080

# STORAGE_SECRET is required for signed browser sessions.
# BACKEND_URL points to the FastAPI service (docker-compose network name).
# Run from the app dir (imports are flat: views/, services/, components/...).
WORKDIR /srv/frontend/app
CMD ["/srv/frontend/.venv/bin/python", "main.py"]
