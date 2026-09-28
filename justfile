# AgentBase: every dev task lives here.
#
# BUILD_SPEC §5 Phase 0: use `just` for every dev task, with no `.sh` or `.bat`.
# Single-command, recipe-local working directories match under `sh` and PowerShell.

set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]
set dotenv-load := false

# ---------------------------------------------------------------------------
# Redirect package caches and dev runtime state to repository `.dev/` so clones
# do not fill the system drive. Tool installs stay external; exports apply only
# to these recipes.
# ---------------------------------------------------------------------------

dev_dir := justfile_directory() / ".dev"

export CARGO_HOME := dev_dir / "cache" / "cargo"
export UV_CACHE_DIR := dev_dir / "cache" / "uv"
export npm_config_cache := dev_dir / "cache" / "npm"

# Dev-only sidecar data directory; shipped apps use OS app-data
# (`agentbase.config.default_data_dir`).
export AGENTBASE_DATA_DIR := dev_dir / "data"

# Keep PyInstaller bootloader cache off the system drive.
export PYINSTALLER_CONFIG_DIR := dev_dir / "cache" / "pyinstaller"

# ---------------------------------------------------------------------------
# Tauri appends the target triple to `externalBin`; any other sidecar name is
# silently missing at bundle time (BUILD_SPEC §5 Phase 1).
# ---------------------------------------------------------------------------

target_triple := if os() == "windows" {
    "x86_64-pc-windows-msvc"
} else if os() == "macos" {
    arch() + "-apple-darwin"
} else {
    arch() + "-unknown-linux-gnu"
}

# Build `sidecar_binary`; use `sidecar_file` on disk because PyInstaller appends
# the extension.
sidecar_binary := "agentbase-sidecar-" + target_triple
exe_suffix := if os() == "windows" { ".exe" } else { "" }
sidecar_file := sidecar_binary + exe_suffix
sidecar_dir := justfile_directory() / "apps" / "desktop" / "src-tauri" / "binaries"

# PyInstaller `--add-data` uses `;` on Windows and `:` elsewhere; wrong values
# silently omit data. Sources must be absolute because paths resolve from `--specpath`.
data_sep := if os() == "windows" { ";" } else { ":" }

# Select bundles per host: `tauri.conf.json` has one cross-host target list;
# `nsis` is meaningless on macOS and `"all"` adds a Windows MSI. Ship macOS as
# `.app` and DMG: a Downloads zip is translocated and absent from Spotlight.
bundle_targets := if os() == "windows" { "nsis" } else { "app,dmg" }

# Cross-check the platform other than this host.
cross_platform := if os() == "windows" { "darwin" } else { "win32" }

# Glob every migration: named files risk frozen-only missing-resource failures.
# A test verifies coverage of all `MIGRATIONS` entries.
migrations_sql := justfile_directory() / "apps" / "backend" / "src" / "agentbase" / "store" / "*.sql"
codex_manifest := justfile_directory() / "apps" / "backend" / "src" / "agentbase" / "providers" / "codex_runtime.json"
sidecar_path := sidecar_dir / sidecar_file

# Commit generated TypeScript API types instead of building on demand.
schemas_dir := justfile_directory() / "packages" / "schemas"

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
# CI and clean clones must pass `just check`.
# ---------------------------------------------------------------------------

# Lint and typecheck everything.
check: setup lint typecheck

# Lint and typecheck everything, then run the test suites.
ci: check test

# ---------------------------------------------------------------------------
# Lint
# ---------------------------------------------------------------------------

# Lint backend and frontend; `ruff format --check` catches silent CRLF changes.
lint: lint-backend lint-backend-format lint-desktop

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

# Typecheck both platforms: `mypy` narrows `sys.platform`, hiding dead branches
# for the other host without a second pass.
typecheck: typecheck-backend typecheck-backend-cross typecheck-desktop

# mypy --strict on the Python sidecar.
[group('typecheck')]
[working-directory('apps/backend')]
typecheck-backend:
    uv run mypy

# mypy --strict as if on the platform this host is not.
[group('typecheck')]
[working-directory('apps/backend')]
typecheck-backend-cross:
    uv run mypy --platform {{ cross_platform }}

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
test: test-backend test-desktop

# pytest on the Python sidecar.
[group('test')]
[working-directory('apps/backend')]
test-backend *ARGS:
    uv run pytest {{ ARGS }}

# Run Vitest for the React frontend, reducer, and dashboard.
[group('test')]
[working-directory('apps/desktop')]
test-desktop *ARGS:
    npm run --silent test -- {{ ARGS }}

# pytest with a coverage summary.
[group('test')]
[working-directory('apps/backend')]
test-backend-cov:
    uv run pytest --cov=agentbase --cov-report=term-missing

# ---------------------------------------------------------------------------
# Generated code
# ---------------------------------------------------------------------------

# Regenerate committed OpenAPI schema and TypeScript types; snapshot tests catch drift.
[group('build')]
[working-directory('apps/backend')]
schemas:
    uv run python -m agentbase.openapi {{ schemas_dir / "openapi.json" }} {{ schemas_dir / "src" / "api.ts" }}

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

# Freeze a self-contained sidecar. `--add-data` includes SQL migrations and the
# Codex manifest that `--onefile` omits. Fetch the App Server runtime on first
# ChatGPT sign-in, avoiding unpacking it every launch.
[group('build')]
[working-directory('apps/backend')]
build-sidecar:
    uv run pyinstaller --onefile --clean --noconfirm --name {{ sidecar_binary }} --distpath {{ sidecar_dir }} --workpath {{ dev_dir / "cache" / "pyinstaller" / "build" }} --specpath {{ dev_dir / "cache" / "pyinstaller" }} --add-data "{{ migrations_sql }}{{ data_sep }}agentbase/store" --add-data "{{ codex_manifest }}{{ data_sep }}agentbase/providers" --exclude-module codex_cli_bin src/agentbase/__main__.py

# Regenerate Codex runtime manifest from `uv.lock` wheel pins.
[group('build')]
[working-directory('apps/backend')]
codex-manifest:
    uv run python -m agentbase.providers.codex_runtime uv.lock {{ codex_manifest }}

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

# Vite dev port; `tauri dev` starts Vite and requires it free.
dev_port := "5173"

# Vite dev server on 127.0.0.1:5173.
[group('run')]
[working-directory('apps/desktop')]
dev-desktop:
    npm run --silent dev

# Run against Vite, rebuilding sidecar first. Check port before rebuilding so a
# leftover server fails early with a useful cause.
[group('run')]
dev-app: _check-dev-port build-sidecar _dev-app

[private]
[working-directory('apps/desktop')]
_dev-app:
    npx --no-install tauri dev

[private]
[windows]
_check-dev-port:
    @$c = Get-NetTCPConnection -LocalPort {{ dev_port }} -State Listen -ErrorAction SilentlyContinue ; if (-not $c) { exit 0 } ; $procId = $c[0].OwningProcess ; $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue ; $name = "unknown" ; if ($proc) { $name = $proc.Name } ; Write-Error "Port {{ dev_port }} is already in use by PID $procId ($name). tauri dev needs it free: a leftover Vite server (dev-desktop, or a dev-app whose tauri process died without it) is still running. Stop it first: taskkill /PID $procId /T /F" ; exit 1

[private]
[unix]
_check-dev-port:
    @pid=$(lsof -ti tcp:{{ dev_port }} -sTCP:LISTEN 2>/dev/null) ; if [ -n "$pid" ]; then echo "Port {{ dev_port }} is already in use by PID $pid ($(ps -o comm= -p "$pid" 2>/dev/null || echo unknown)). tauri dev needs it free: a leftover Vite server (dev-desktop, or a dev-app whose tauri process died without it) is still running. Stop it first: kill $pid" >&2 ; exit 1 ; fi

# Lint Rust without a binary. `tauri-build` validates `externalBin` on every
# Cargo invocation, including Clippy, so `binaries/` needs a frozen sidecar.
[group('build')]
[working-directory('apps/desktop/src-tauri')]
check-tauri:
    cargo clippy --all-targets -- -D warnings

# Build NSIS on Windows and `.app` on macOS. Depend on setup and rebuild sidecar
# to prevent stale bundling.
[group('build')]
build-installer: setup build-sidecar _build-installer

[private]
[linux]
[windows]
[working-directory('apps/desktop')]
_build-installer:
    npx --no-install tauri build --bundles {{ bundle_targets }}

# `CI=true` skips Tauri's Finder-layout AppleScript, which requires manual
# Automation permission. Match GitHub's user-downloadable DMG locally.
[private]
[macos]
[working-directory('apps/desktop')]
_build-installer:
    CI=true npx --no-install tauri build --bundles {{ bundle_targets }}

# Verify sidecar and installer only after build. `--require-build-checks` turns
# skipped missing artifacts into named release failures.
[group('build')]
[working-directory('apps/backend')]
verify-build: setup
    uv run pytest tests/test_sidecar_binary.py tests/test_installer_bundle.py tests/test_macos_dmg.py --require-build-checks -v

# Install and run with Python absent from PATH: §5 Phase 9's proxy for a second
# Windows machine. It changes installed software, so omit it from `just test`.
# `AGENTBASE_INSTALLER_DIR` can select another installer location.
[group('build')]
[working-directory('apps/backend')]
verify-installed: setup
    uv run pytest tests/test_installed_app.py --install-smoke -v

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
    @echo "dev runtime data {{ AGENTBASE_DATA_DIR }}"
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
