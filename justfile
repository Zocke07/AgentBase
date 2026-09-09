# AgentSpace — every dev task lives here.
#
# BUILD_SPEC §5 Phase 0: `just` recipes for every dev task, no `.sh` and no
# `.bat` files anywhere. Recipes are single commands run from a per-recipe
# working directory, so they behave identically under `sh` and PowerShell.

set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]
set dotenv-load := false

# List every available recipe.
default:
    @just --list --unsorted

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

# Install backend and frontend dependencies.
setup: setup-backend setup-desktop

# Create the backend venv and sync locked dependencies.
[group('setup')]
[working-directory('apps/backend')]
setup-backend:
    uv sync --all-groups

# Install frontend dependencies from the lockfile.
[group('setup')]
[working-directory('apps/desktop')]
setup-desktop:
    npm install --no-audit --no-fund

# ---------------------------------------------------------------------------
# The gate: `just check` is what CI runs and what must pass on a clean clone.
# ---------------------------------------------------------------------------

# Lint and typecheck everything.
check: setup lint typecheck

# Lint and typecheck everything, then run the test suites.
ci: check test

# ---------------------------------------------------------------------------
# Lint
# ---------------------------------------------------------------------------

# Lint backend and frontend.
lint: lint-backend lint-desktop

# ruff check on the Python sidecar.
[group('lint')]
[working-directory('apps/backend')]
lint-backend:
    uv run ruff check .

# ruff format --check on the Python sidecar.
[group('lint')]
[working-directory('apps/backend')]
lint-backend-format:
    uv run ruff format --check .

# eslint on the React frontend, including case-sensitive import paths.
[group('lint')]
[working-directory('apps/desktop')]
lint-desktop:
    npm run --silent lint

# ---------------------------------------------------------------------------
# Typecheck
# ---------------------------------------------------------------------------

# Typecheck backend and frontend.
typecheck: typecheck-backend typecheck-desktop

# mypy --strict on the Python sidecar.
[group('typecheck')]
[working-directory('apps/backend')]
typecheck-backend:
    uv run mypy

# tsc --noEmit on the React frontend.
[group('typecheck')]
[working-directory('apps/desktop')]
typecheck-desktop:
    npm run --silent typecheck

# ---------------------------------------------------------------------------
# Format
# ---------------------------------------------------------------------------

# Apply formatting and safe autofixes everywhere.
fmt: fmt-backend fmt-desktop

# ruff format + ruff --fix on the Python sidecar.
[group('fmt')]
[working-directory('apps/backend')]
fmt-backend:
    uv run ruff format . ; uv run ruff check --fix .

# eslint --fix on the React frontend.
[group('fmt')]
[working-directory('apps/desktop')]
fmt-desktop:
    npm run --silent lint:fix

# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

# Run every test suite.
test: test-backend

# pytest on the Python sidecar.
[group('test')]
[working-directory('apps/backend')]
test-backend *ARGS:
    uv run pytest {{ ARGS }}

# pytest with a coverage summary.
[group('test')]
[working-directory('apps/backend')]
test-backend-cov:
    uv run pytest --cov=agentspace --cov-report=term-missing

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

# Vite dev server on 127.0.0.1:5173.
[group('run')]
[working-directory('apps/desktop')]
dev-desktop:
    npm run --silent dev

# Production build of the frontend bundle.
[group('run')]
[working-directory('apps/desktop')]
build-desktop:
    npm run --silent build

# ---------------------------------------------------------------------------
# Housekeeping
# ---------------------------------------------------------------------------

# Show the resolved toolchain versions.
[group('misc')]
versions:
    @just --version ; uv --version ; node --version ; npm --version

# Delete every git-ignored file: node_modules, .venv, caches, dist, target.
[confirm("Delete all git-ignored files (node_modules, .venv, dist, target)?")]
[group('misc')]
clean:
    git clean -Xdf
