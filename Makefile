# Infrastructures — dependency & ops helpers.
# `make help` lists all targets.

.DEFAULT_GOAL := help

help:  ## List available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "} {printf "  \033[1m%-18s\033[0m %s\n", $$1, $$2}'

up:  ## Build and start the full stack (with Keycloak)
	docker compose --profile keycloak up -d --build

down:  ## Stop the stack
	docker compose --profile keycloak down

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

.PHONY: help up down outdated versions lock upgrade
