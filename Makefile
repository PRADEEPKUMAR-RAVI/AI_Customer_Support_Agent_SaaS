# Phase-0 developer targets. Stack targets use docker compose; host targets use the local
# .venv. Picks the venv python for Windows (.venv/Scripts) or Unix (.venv/bin) automatically.
VENV_PY := $(if $(wildcard .venv/Scripts/python.exe),.venv/Scripts/python.exe,.venv/bin/python)

.PHONY: help up down reset logs migrate seed export test test-rls lint fe-install fe-gen fe-test fe-dev

help:
	@echo "up/down/logs           - full docker stack"
	@echo "migrate/seed/export    - run against the local .venv (needs a reachable Postgres)"
	@echo "test / test-rls / lint - backend checks"
	@echo "fe-install/gen/test/dev- frontend (FE-Shell)"

# --- full stack ---------------------------------------------------------------------------
up:
	docker compose up --build

down:
	docker compose down

# Clean slate: remove the Postgres volume so the next `up` re-migrates + re-inits the cs_* roles
# from scratch. DESTRUCTIVE (wipes all tenants/data) — dev only. Then: `make up` and re-seed.
reset:
	docker compose down -v
	@echo "Volumes removed. Run 'make up', then seed: docker compose exec api python -m app.cli.seed"

logs:
	docker compose logs -f

# --- backend (host / .venv) ---------------------------------------------------------------
migrate:
	$(VENV_PY) -m alembic upgrade head

seed:
	$(VENV_PY) -m app.cli.seed

export:
	$(VENV_PY) -m app.cli.export_openapi

# Pure/unit CI gates (no external services): transitions, verify, sse-contract, ssrf, crypto.
test:
	$(VENV_PY) -m pytest -q

# The two-tenant RLS leak test — needs a LIVE Postgres with the migration applied + cs_app role
# (e.g. `make up` in another shell, or a CI postgres service). See README.
test-rls:
	RUN_RLS_TESTS=1 $(VENV_PY) -m pytest -q -m rls

lint:
	$(VENV_PY) -m ruff check app

# --- frontend (FE-Shell) ------------------------------------------------------------------
fe-install:
	cd frontend && npm ci

fe-gen:
	cd frontend && npm run gen:api

fe-test:
	cd frontend && npm run test

fe-dev:
	cd frontend && npm run dev
