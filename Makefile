# Every target is safe to re-run. Python work goes through uv; UI work goes through npm scripts.
UV ?= uv
export PII_HASH_KEY ?= local-dev-key-not-for-deployment

.PHONY: dev dev-api dev-ui test lint spec schema integration ui-install ui-test e2e

# The API on the in-memory store with local adapters, plus the UI dev server. Gemini needs a
# GCP project, so the advisor and assistant stay off unless you export GCP_PROJECT and turn
# them on (ADVISOR_ENABLED=true ASSISTANT_ENABLED=true make dev).
ADVISOR_ENABLED ?= false
ASSISTANT_ENABLED ?= false

dev:
	$(MAKE) -j2 dev-api dev-ui

dev-api:
	CUSTOMER_STORE=memory ALLOW_LOCAL_ADAPTERS=true EMAIL_ALLOW_RESERVED_DOMAINS=true \
	CORS_ALLOW_ORIGINS=http://localhost:3000 \
	ADVISOR_ENABLED=$(ADVISOR_ENABLED) ASSISTANT_ENABLED=$(ASSISTANT_ENABLED) \
	$(UV) run --frozen uvicorn app.main:create_app --factory --reload --port 8000

dev-ui: ui-install
	cd ui && API_BASE_URL=http://localhost:8000 \
	ASSISTANT_ENABLED=$(ASSISTANT_ENABLED) BOT_CHECK_STUB_TOKEN=local npm run dev

# Offline suite: no credentials, no network. The integration marker is deselected.
test:
	$(UV) run --frozen pytest

lint:
	$(UV) run --frozen ruff check .
	$(UV) run --frozen ruff format --check .
	$(UV) run --frozen mypy

# Regenerate the OpenAPI document and the UI's typed client from it.
spec: ui-install
	$(UV) run --frozen python -m scripts.export_openapi
	cd ui && npm run gen:api

# Apply the BigQuery DDL. Needs GCP_PROJECT and credentials. A second run changes nothing.
schema:
	$(UV) run --frozen python -m scripts.apply_schema

# Platform check against a real dev project. Needs GCP_PROJECT and credentials.
integration:
	$(UV) run --frozen pytest -m integration tests/integration -o addopts=""

ui-install:
	@test -d ui/node_modules || (cd ui && npm ci --no-audit --no-fund)

ui-test: ui-install
	cd ui && npm run lint && npm run typecheck && npm test

e2e: ui-install
	cd ui && npx playwright install chromium && npm run e2e
