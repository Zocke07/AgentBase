# AgentSpace — every dev task lives here.
#
# BUILD_SPEC §5 Phase 0: `just` recipes for every dev task, no `.sh` and no
# `.bat` files anywhere. Recipes are single commands run from a per-recipe
# working directory, so they behave identically under `sh` and PowerShell.

set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]
set dotenv-load := false

# ---------------------------------------------------------------------------
# Everything that grows lives inside the repository.
#
# Tool *installations* stay where their installers put them (rustup toolchains,
# VS Build Tools, uv's Python builds, Node). What is redirected here is the data
# those tools generate — package caches and this application's own runtime state
# — so that a clone on a roomy drive does not quietly fill the system drive.
#
# These are `just` exports, so they apply to this repository's recipes only and
# need no shell profile edits. Your other projects keep using the shared
# machine-wide caches.
#
# `target/`, `node_modules/` and `.venv/` are already inside the repo by virtue
# of where they are created, so they need no redirection.
# ---------------------------------------------------------------------------

dev_dir := justfile_directory() / ".dev"

export CARGO_HOME := dev_dir / "cache" / "cargo"
export UV_CACHE_DIR := dev_dir / "cache" / "uv"
export npm_config_cache := dev_dir / "cache" / "npm"

# Dev-only override of the sidecar's data directory. The shipped application
# still resolves the OS app-data dir (BUILD_SPEC §5 Phase 2) — see
# `agentspace.config.default_data_dir`. This only affects `just` recipes, so a
# dev run's SQLite file, logs and agent workspace stay in the working tree where
# they can be inspected and deleted, instead of in %LOCALAPPDATA%.
export AGENTSPACE_DATA_DIR := dev_dir / "data"

# PyInstaller caches its prebuilt bootloader here; without this it writes to
# %APPDATA%/pyinstaller on the system drive.
export PYINSTALLER_CONFIG_DIR := dev_dir / "cache" / "pyinstaller"

# ---------------------------------------------------------------------------
# Sidecar naming.
#
# Tauri resolves an `externalBin` entry by appending the *target triple* to the
# configured name — `binaries/agentspace-sidecar` is looked up on disk as
# `binaries/agentspace-sidecar-x86_64-pc-windows-msvc.exe`. A binary named
# anything else, including a plain `.exe`, is silently not found at bundle time.
# BUILD_SPEC §5 Phase 1 calls this out as a trap; it is encoded here rather than
# left to a human to remember.
#
# v1 ships x86_64 Windows only. macOS is computed so the CI build job works from
# day one (§1 constraint 7), not because a Mac artifact is published.
# ---------------------------------------------------------------------------

target_triple := if os() == "windows" {
    "x86_64-pc-windows-msvc"
} else if os() == "macos" {
    arch() + "-apple-darwin"
} else {
    arch() + "-unknown-linux-gnu"
}

# The name Tauri is configured with, plus the triple. PyInstaller appends the
# platform's executable extension itself, so `sidecar_file` is what exists on
# disk while `sidecar_binary` is what the build is asked to produce.
sidecar_binary := "agentspace-sidecar-" + target_triple
exe_suffix := if os() == "windows" { ".exe" } else { "" }
sidecar_file := sidecar_binary + exe_suffix
sidecar_dir := justfile_directory() / "apps" / "desktop" / "src-tauri" / "binaries"
sidecar_path := sidecar_dir / sidecar_file

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

# Freeze the sidecar into a single self-contained executable.
[group('build')]
[working-directory('apps/backend')]
build-sidecar:
    uv run pyinstaller --onefile --clean --noconfirm --name {{ sidecar_binary }} --distpath {{ sidecar_dir }} --workpath {{ dev_dir / "cache" / "pyinstaller" / "build" }} --specpath {{ dev_dir / "cache" / "pyinstaller" }} src/agentspace/__main__.py

# Show the built sidecar's path, size and hash.
[group('build')]
versions-sidecar:
    @just _hash "{{ sidecar_path }}"

[private]
[windows]
_hash path:
    @$f = Get-Item "{{ path }}" ; Write-Output $f.FullName ; Write-Output "  $($f.Length) bytes" ; Write-Output "  sha256 $((Get-FileHash -Algorithm SHA256 $f).Hash)"

[private]
[unix]
_hash path:
    @echo "{{ path }}" ; echo "  $(wc -c < '{{ path }}') bytes" ; echo "  sha256 $(shasum -a 256 '{{ path }}' | cut -d' ' -f1)"

# Vite dev server on 127.0.0.1:5173.
[group('run')]
[working-directory('apps/desktop')]
dev-desktop:
    npm run --silent dev

# Run the desktop app against the dev server. Rebuilds the sidecar first.
[group('run')]
dev-app: build-sidecar _dev-app

[private]
[working-directory('apps/desktop')]
_dev-app:
    npx --no-install tauri dev

# Typecheck the Rust shell without producing a binary.
[group('build')]
[working-directory('apps/desktop/src-tauri')]
check-tauri:
    cargo clippy --all-targets -- -D warnings

# Build the Windows NSIS installer. Rebuilds the sidecar first so the bundle
# can never pick up a stale one (BUILD_SPEC §5 Phase 1).
[group('build')]
build-installer: build-sidecar _build-installer

[private]
[working-directory('apps/desktop')]
_build-installer:
    npx --no-install tauri build

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

# Show where every generated file goes.
[group('misc')]
paths:
    @echo "cargo registry   {{ CARGO_HOME }}"
    @echo "uv cache         {{ UV_CACHE_DIR }}"
    @echo "npm cache        {{ npm_config_cache }}"
    @echo "dev runtime data {{ AGENTSPACE_DATA_DIR }}"
    @echo "backend venv     {{ justfile_directory() / 'apps' / 'backend' / '.venv' }}"
    @echo "node_modules     {{ justfile_directory() / 'apps' / 'desktop' / 'node_modules' }}"

# Delete the redirected caches and dev data, keeping installed dependencies.
[confirm("Delete .dev/ (package caches and dev runtime data)?")]
[group('misc')]
clean-dev:
    git clean -Xdf -- .dev

# Delete every git-ignored file: node_modules, .venv, .dev caches, dist, target.
[confirm("Delete ALL git-ignored files (node_modules, .venv, .dev, dist, target)?")]
[group('misc')]
clean:
    git clean -Xdf
