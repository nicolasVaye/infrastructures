# Infrastructures — dependency & ops helpers.
# `make help` lists all targets.

.DEFAULT_GOAL := help

PY := python3

help:  ## List available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "} {printf "  \033[1m%-18s\033[0m %s\n", $$1, $$2}'

# ── Docker: everyday lifecycle ──────────────────────────────────────────────

up:  ## Build and start the full stack (with Keycloak)
	docker compose --profile keycloak up -d --build

rebuild:  ## Force a full rebuild + recreate of every container (picks up code changes)
	docker compose --profile keycloak down
	docker compose --profile keycloak build --no-cache
	docker compose --profile keycloak up -d --force-recreate

restart:  ## Restart the containers WITHOUT rebuilding (config/panic reload)
	docker compose --profile keycloak restart

logs:  ## Tail the logs of every service
	docker compose logs -f --tail=100

ps:  ## Show container status (health included)
	docker compose ps

down:  ## Stop the stack
	docker compose --profile keycloak down

# ── Tests & quality (the CI gate, runnable locally) ────────────────────────

test-backend:  ## Run backend tests (SQLite, in-process, no Docker needed)
	@echo "==> backend tests (pytest, SQLite in-process)"
	cd backend && uv sync --extra dev --quiet && uv run --extra dev pytest -q
	@echo "==> backend: PASSED"

test-frontend:  ## Byte-compile + i18n gate for the frontend (no runtime needed)
	@echo "==> frontend gates (byte-compile + i18n)"
	$(PY) -m compileall -q frontend/app shared/src
	$(PY) scripts/check_i18n.py
	@echo "==> frontend: PASSED"

test: test-backend test-frontend  ## Run every check the CI runs (backend + frontend)
	@echo "==> ALL TESTS PASSED"

perf:  ## Time every UI endpoint against the RUNNING stack (login + p50/p95)
	PERF_PASSWORD=$${PERF_PASSWORD:?export PERF_PASSWORD first} \
	  $(PY) scripts/perf_probe.py

perf-ui:  ## Browser-level page-load timing (needs: uv run --with playwright -- playwright install chromium)
	$(PY) scripts/perf_ui.py

test-sse-ui:  ## Live-update acceptance test: login/avatar/logout seen from an open /settings page
	PERF_UI_PASSWORD=$${PERF_UI_PASSWORD:?export PERF_UI_PASSWORD first} \
	  uv run --with playwright -- $(PY) scripts/sse_check.py

test-identity-ui:  ## Identity swap from a 2nd tab must reload the 1st tab's stale page
	PERF_UI_PASSWORD=$${PERF_UI_PASSWORD:?export PERF_UI_PASSWORD first} \
	  uv run --with playwright -- $(PY) scripts/identity_check.py

check:  ## CI gate exactly as GitHub Actions runs it
	@echo "==> CI gate (compileall + i18n + pytest)"
	$(PY) -m compileall -q backend/app frontend/app shared/src
	$(PY) scripts/check_i18n.py
	cd backend && uv sync --extra dev --quiet && uv run --extra dev pytest -q
	@echo "==> CI GATE: PASSED"

# ── Local development (uv, no Docker) ────────────────────────────────────────

dev-backend:  ## Run the API locally with auto-reload (SQLite fallback, INSECURE_DEV)
	cd backend && INSECURE_DEV=1 $${JWT_SECRET:-dev-secret-dev-secret-dev-secret-32ch} \
	  uv run uvicorn app.main:app --reload --port 8000

dev-worker:  ## Run one worker locally (needs a running backend DB)
	cd backend && INSECURE_DEV=1 uv run python -m app.worker

dev-frontend:  ## Run the NiceGUI frontend locally against the local backend
	cd frontend/app && BACKEND_URL=http://localhost:8000 uv run python main.py

# ── Swarm deployment (production, multi-node) ──────────────────────────────

swarm-init:  ## Initialize the local Docker host as a single-node Swarm
	docker swarm init

swarm-deploy:  ## Deploy the production stack (docker-stack.yaml, needs .env)
	docker stack deploy -c docker-stack.yaml --with-registry-auth infrastructures

swarm-ps:  ## Show the stack's services and replicas
	docker stack ps infrastructures

swarm-logs:  ## Tail the stack's logs (all services)
	docker service logs -f --tail=100 infrastructures

swarm-scale:  ## Scale: make swarm-scale BACKEND=5 WORKER=8 (defaults 3/4)
	docker service scale infrastructures_backend=$${BACKEND:-3} \
	  infrastructures_worker=$${WORKER:-4}

swarm-remove:  ## Remove the production stack (data volumes are kept)
	docker stack rm infrastructures

# ── Housekeeping ────────────────────────────────────────────────────────────

outdated:  ## List available upgrades for installed packages (frontend + backend)
	@echo "── frontend (uv) ───────────────────────────────"
	@docker compose exec frontend uv pip list --outdated 2>/dev/null || \
	  echo "(frontend not running — run 'make up' first)"
	@echo ""
	@echo "── backend / workers (uv) ──────────────────────"
	@docker compose exec backend uv pip list --outdated 2>/dev/null || \
	  echo "(backend not running — run 'make up' first)"

versions:  ## Show the versions actually running in the containers
	@docker compose exec frontend uv pip list 2>/dev/null | head -30
	@docker compose exec backend uv pip list 2>/dev/null | head -30

# Both components resolve from their pyproject.toml and write uv.lock —
# commit the lockfiles! The Dockerfiles copy uv.lock when present, so a
# committed lock makes every image build install the exact same tree.
lock:  ## (re)generate backend/uv.lock + frontend/uv.lock → commit both
	cd backend && uv lock
	cd frontend && uv lock

upgrade:  ## Refresh both lockfiles to the newest compatible versions
	cd backend && uv lock --upgrade
	cd frontend && uv lock --upgrade

.PHONY: help up rebuild restart logs ps down test-backend test-frontend test \
        check dev-backend dev-worker dev-frontend swarm-init swarm-deploy \
        swarm-ps swarm-logs swarm-scale swarm-remove outdated versions lock \
        upgrade perf perf-ui test-sse-ui test-identity-ui
