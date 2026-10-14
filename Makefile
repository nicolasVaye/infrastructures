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
	@echo "── frontend (pip) ──────────────────────────────"
	@docker compose exec frontend pip list --outdated 2>/dev/null || \
	  echo "(frontend not running — run 'make up' first)"
	@echo ""
	@echo "── backend / workers (uv) ──────────────────────"
	@docker compose exec backend uv pip list --outdated 2>/dev/null || \
	  echo "(backend not running — run 'make up' first)"

versions:  ## Show the versions actually running in the containers
	@docker compose exec frontend pip show nicegui 2>/dev/null | grep -E '^(Name|Version)'
	@docker compose exec backend uv pip list 2>/dev/null | head -30

# Backend: uv resolves pyproject.toml and writes backend/uv.lock — commit it!
# The Dockerfile already copies uv.lock when present, so a committed lock
# makes every image build install the exact same dependency tree.
lock:  ## (re)generate backend/uv.lock from pyproject — run in backend/, commit the file
	cd backend && uv lock

upgrade:  ## Refresh backend/uv.lock to the newest compatible versions
	cd backend && uv lock --upgrade

# Frontend: the image installs from the pinned versions in frontend/Dockerfile
# (nicegui) — bump the pin there and in frontend/pyproject.toml together.

.PHONY: help up down outdated versions lock upgrade
