# AgentBase: every dev task lives here.
#
# BUILD_SPEC §5 Phase 0: `just` recipes for every dev task, no `.sh` and no
# `.bat` files anywhere. Recipes are single commands run from a per-recipe
# working directory, so they behave identically under `sh` and PowerShell.

set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]
set dotenv-load := false

# ---------------------------------------------------------------------------
# Everything that grows lives inside the repository: package caches and this
# application's dev runtime state are redirected into `.dev/`, so a clone on
# a roomy drive does not fill the system drive. Tool installations stay where
# their installers put them. These are `just` exports, so they apply to this
# repository's recipes only.
# ---------------------------------------------------------------------------

dev_dir := justfile_directory() / ".dev"

export CARGO_HOME := dev_dir / "cache" / "cargo"
export UV_CACHE_DIR := dev_dir / "cache" / "uv"
export npm_config_cache := dev_dir / "cache" / "npm"

# Dev-only override of the sidecar's data directory; the shipped application
# still resolves the OS app-data dir (`agentbase.config.default_data_dir`).
export AGENTBASE_DATA_DIR := dev_dir / "data"

# PyInstaller's bootloader cache, which would otherwise land on the system drive.
export PYINSTALLER_CONFIG_DIR := dev_dir / "cache" / "pyinstaller"

# ---------------------------------------------------------------------------
# Sidecar naming. Tauri resolves an `externalBin` entry by appending the
# target triple to the configured name; a binary named anything else is
# silently not found at bundle time (BUILD_SPEC §5 Phase 1).
# ---------------------------------------------------------------------------

target_triple := if os() == "windows" {
    "x86_64-pc-windows-msvc"
} else if os() == "macos" {
    arch() + "-apple-darwin"
} else {
    arch() + "-unknown-linux-gnu"
}

# `sidecar_binary` is what the build is asked to produce; `sidecar_file` is
# what exists on disk, since PyInstaller appends the extension itself.
sidecar_binary := "agentbase-sidecar-" + target_triple
exe_suffix := if os() == "windows" { ".exe" } else { "" }
sidecar_file := sidecar_binary + exe_suffix
sidecar_dir := justfile_directory() / "apps" / "desktop" / "src-tauri" / "binaries"

# PyInstaller's --add-data separator is ";" on Windows and ":" elsewhere; the
# wrong one is a silently missing data file. The source path must be absolute,
# since relative paths resolve against --specpath.
data_sep := if os() == "windows" { ";" } else { ":" }

# What `tauri build` is asked to produce, per platform. `tauri.conf.json`'s
# `bundle.targets` is one list for every host, and `nsis` means nothing on
# macOS; `"all"` would also build a per-machine MSI on Windows. macOS gets
# the `.app` and the disk image users download: a bare zip left the app in
# Downloads, where Gatekeeper runs a translocated copy on every launch and
# Spotlight never lists it. The image's Applications link is the install step.
bundle_targets := if os() == "windows" { "nsis" } else { "app,dmg" }

# The platform `just typecheck` cross-checks: whichever one this host is not.
cross_platform := if os() == "windows" { "darwin" } else { "win32" }

# Every migration, as a glob: a named file would need an edit here per
# migration, and forgetting it is a binary that dies on a missing resource
# only when frozen. A test asserts the glob covers every MIGRATIONS entry.
migrations_sql := justfile_directory() / "apps" / "backend" / "src" / "agentbase" / "store" / "*.sql"
codex_manifest := justfile_directory() / "apps" / "backend" / "src" / "agentbase" / "providers" / "codex_runtime.json"
sidecar_path := sidecar_dir / sidecar_file

# Generated TypeScript API types, committed rather than built on demand.
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
# The gate: `just check` is what CI runs and what must pass on a clean clone.
# ---------------------------------------------------------------------------

# Lint and typecheck everything.
check: setup lint typecheck

# Lint and typecheck everything, then run the test suites.
ci: check test

# ---------------------------------------------------------------------------
# Lint
# ---------------------------------------------------------------------------

# Lint backend and frontend. `ruff format --check` is in the gate because it
# was once the only check that noticed six files silently converted to CRLF.
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

# Typecheck backend and frontend. The backend is checked twice, once per
# platform: `mypy` narrows `sys.platform` to the host, so a branch dead on the
# other platform is invisible without the second pass.
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

# vitest on the React frontend: the run reducer and the dashboard it renders.
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

# Regenerate packages/schemas from the sidecar's OpenAPI schema. Both outputs
# are committed; `test_openapi_snapshot.py` fails if either drifts.
[group('build')]
[working-directory('apps/backend')]
schemas:
    uv run python -m agentbase.openapi {{ schemas_dir / "openapi.json" }} {{ schemas_dir / "src" / "api.ts" }}

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

# Freeze the sidecar into a single self-contained executable. --add-data
# carries the migration SQL and the Codex runtime manifest, which `--onefile`
# would otherwise omit. The Codex App Server runtime itself is excluded: it is
# fetched into the data directory on the first ChatGPT sign-in, because a
# one-file sidecar unpacks everything it carries on every launch.
[group('build')]
[working-directory('apps/backend')]
build-sidecar:
    uv run pyinstaller --onefile --clean --noconfirm --name {{ sidecar_binary }} --distpath {{ sidecar_dir }} --workpath {{ dev_dir / "cache" / "pyinstaller" / "build" }} --specpath {{ dev_dir / "cache" / "pyinstaller" }} --add-data "{{ migrations_sql }}{{ data_sep }}agentbase/store" --add-data "{{ codex_manifest }}{{ data_sep }}agentbase/providers" --exclude-module codex_cli_bin src/agentbase/__main__.py

# Regenerate the Codex runtime manifest from the wheels `uv.lock` pins.
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

# Vite's dev port. `tauri dev` starts Vite itself and needs this free.
dev_port := "5173"

# Vite dev server on 127.0.0.1:5173.
[group('run')]
[working-directory('apps/desktop')]
dev-desktop:
    npm run --silent dev

# Run the desktop app against the dev server. Rebuilds the sidecar first;
# checks the Vite port before that, since a leftover server otherwise fails
# only after the rebuild, with a message naming neither process nor cause.
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

# Lint the Rust shell without producing a binary. Needs a frozen sidecar in
# `binaries/` first: `tauri-build` validates `externalBin` on every cargo
# invocation, clippy included.
[group('build')]
[working-directory('apps/desktop/src-tauri')]
check-tauri:
    cargo clippy --all-targets -- -D warnings

# Build the installer: NSIS on Windows, a .app on macOS. Depends on `setup`
# so it works on a clean clone, and rebuilds the sidecar first so the bundle
# can never pick up a stale one.
[group('build')]
build-installer: setup build-sidecar _build-installer

[private]
[linux]
[windows]
[working-directory('apps/desktop')]
_build-installer:
    npx --no-install tauri build --bundles {{ bundle_targets }}

# `CI=true` makes Tauri's dmg script skip the Finder AppleScript that lays out
# the image's window. That step needs Automation permission for Finder, which
# a fresh terminal has to be granted by hand, and GitHub's runners skip it
# anyway; so a local image is built the same way as the one users download.
[private]
[macos]
[working-directory('apps/desktop')]
_build-installer:
    CI=true npx --no-install tauri build --bundles {{ bundle_targets }}

# Check the built sidecar and installer: run AFTER a build, never before.
# These tests skip when nothing is built, which is wrong for a release, so
# `--require-build-checks` turns a missing artefact into a named failure.
[group('build')]
[working-directory('apps/backend')]
verify-build: setup
    uv run pytest tests/test_sidecar_binary.py tests/test_installer_bundle.py tests/test_macos_dmg.py --require-build-checks -v

# Install the built installer here and run it with no Python on PATH: §5
# Phase 9's "second Windows machine", as close as one machine can state it.
# It installs software, so it is never part of `just test`.
# `AGENTBASE_INSTALLER_DIR` points it at an installer elsewhere.
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
