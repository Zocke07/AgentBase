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

# PyInstaller's --add-data separator is platform-specific: ";" on Windows,
# ":" elsewhere. Getting it wrong is not an error, it is a silently missing
# data file that only surfaces when the frozen binary first reads it.
#
# The source path must be absolute: --add-data resolves relative paths against
# --specpath, which points into .dev/cache, not against the recipe's working
# directory.
data_sep := if os() == "windows" { ";" } else { ":" }

# What `tauri build` is asked to produce, per platform.
#
# `tauri.conf.json` cannot express this: its `bundle.targets` is a single list
# applied to whatever host is building, and `nsis` means nothing on macOS. The
# alternative, `"targets": "all"`, would additionally build an MSI on Windows —
# a per-machine installer, which contradicts the per-user NSIS install Phase 1
# settled on and verified.
#
# macOS gets `app` and not `dmg` deliberately. §5 Phase 9 builds macOS to catch
# cross-platform breakage and explicitly does not publish it; a `.app` is the
# Tauri bundle, and everything that can break in *our* code — the PyInstaller
# freeze, the Rust compile, `externalBin` resolution — has already happened by
# the time it exists. A dmg is hdiutil re-packaging an app that already built,
# so it adds a CI-flaky step that can only fail for reasons unrelated to this
# repository, and a red CI nobody trusts is worse than one less artefact.
bundle_targets := if os() == "windows" { "nsis" } else { "app" }

# Every migration, not just the first. A named `schema.sql` was correct while
# migration 001 was the only one; naming files individually means each new
# migration needs an edit here, and forgetting it produces a binary that starts
# and then dies on a missing resource — a failure invisible to `just ci` and to
# every dev run, because those read the file straight off the source tree.
# `test_migration_sql_is_bundled` asserts this glob covers every MIGRATIONS
# entry, so the omission fails a test instead of a release.
migrations_sql := justfile_directory() / "apps" / "backend" / "src" / "agentspace" / "store" / "*.sql"
sidecar_path := sidecar_dir / sidecar_file

# Generated TypeScript API types, per BUILD_SPEC §3's layout. Committed rather
# than built on demand — see `just schemas`.
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

# Lint backend and frontend.
#
# `lint-backend-format` is in here rather than standing alone because of a real
# Phase 4 incident: a helper script writing source with `Path.write_text()`
# converted six LF files to CRLF, and `ruff check`, `mypy` and `pytest` all
# stayed green — `ruff format --check` was the only thing that noticed, and it
# was the one check `just check` did not run. Phase 9 owns what the gate runs,
# so it runs this too. It found ten already-drifted files the moment it was
# added, all of them Phase 8's.
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

# Typecheck backend and frontend.
#
# The backend is typechecked twice, once per platform this project targets.
# `mypy` narrows `sys.platform` to the host it runs on, so a Windows-only run
# cannot see a branch that is dead on macOS — which is not hypothetical: it is
# how CI run #2 failed, on a `warn_unreachable` error in a platform branch that
# was clean here and broken there. `--platform darwin` reproduces that on this
# machine in twenty seconds instead of a push and a five-minute round trip.
typecheck: typecheck-backend typecheck-backend-macos typecheck-desktop

# mypy --strict on the Python sidecar.
[group('typecheck')]
[working-directory('apps/backend')]
typecheck-backend:
    uv run mypy

# mypy --strict as if on macOS, which CI builds and this machine cannot run.
[group('typecheck')]
[working-directory('apps/backend')]
typecheck-backend-macos:
    uv run mypy --platform darwin

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

# vitest on the React frontend — the run reducer and the dashboard it renders.
[group('test')]
[working-directory('apps/desktop')]
test-desktop *ARGS:
    npm run --silent test -- {{ ARGS }}

# pytest with a coverage summary.
[group('test')]
[working-directory('apps/backend')]
test-backend-cov:
    uv run pytest --cov=agentspace --cov-report=term-missing

# ---------------------------------------------------------------------------
# Generated code
# ---------------------------------------------------------------------------

# Regenerate packages/schemas from the sidecar's OpenAPI schema.
#
# BUILD_SPEC §5 Phase 7: "Generate TS types from the FastAPI OpenAPI schema;
# never hand-write the API types." Both outputs are committed, so `just check`
# on a clean clone never needs a Python environment to typecheck the frontend —
# and `test_openapi_snapshot.py` fails if either drifts from the running app,
# which is what stops a regeneration being forgotten.
[group('build')]
[working-directory('apps/backend')]
schemas:
    uv run python -m agentspace.openapi {{ schemas_dir / "openapi.json" }} {{ schemas_dir / "src" / "api.ts" }}

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

# Freeze the sidecar into a single self-contained executable.
#
# --add-data carries the migration SQL, which `--onefile` would otherwise omit:
# bytecode is collected automatically, data files are not. The failure mode is
# a binary that starts and then cannot create its database.
#
# The source is a glob so that adding a migration needs no edit here.
[group('build')]
[working-directory('apps/backend')]
build-sidecar:
    uv run pyinstaller --onefile --clean --noconfirm --name {{ sidecar_binary }} --distpath {{ sidecar_dir }} --workpath {{ dev_dir / "cache" / "pyinstaller" / "build" }} --specpath {{ dev_dir / "cache" / "pyinstaller" }} --add-data "{{ migrations_sql }}{{ data_sep }}agentspace/store" src/agentspace/__main__.py

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

# Lint the Rust shell without producing a binary.
#
# Needs a frozen sidecar in `binaries/` first. `tauri-build`'s build script
# validates `externalBin` on every cargo invocation, clippy included, so without
# one this fails on a missing resource path rather than on anything it linted.
# Run `just build-sidecar` first, or run this after a build.
[group('build')]
[working-directory('apps/desktop/src-tauri')]
check-tauri:
    cargo clippy --all-targets -- -D warnings

# Depends on `setup` for the same reason `check` does: it has to work on a clean
# clone. `tauri build` is resolved with `npx --no-install`, and its
# `beforeBuildCommand` is `npm run build`, so without `node_modules` it fails on
# npm's unhelpful "could not determine executable to run". That is how CI run #4
# failed on both platforms — after freezing the sidecar successfully — while
# working on every dev machine, where `node_modules` is always already there.
#
# The sidecar is rebuilt first so the bundle can never pick up a stale one
# (BUILD_SPEC §5 Phase 1).
#
# Build the installer: NSIS on Windows, a .app on macOS.
[group('build')]
build-installer: setup build-sidecar _build-installer

[private]
[working-directory('apps/desktop')]
_build-installer:
    npx --no-install tauri build --bundles {{ bundle_targets }}

# Verify the built artefacts, refusing to skip if one is missing.
#
# These tests skip when nothing is built, which is right for `just test` and
# wrong for a release: a CI job that builds an installer and then skips the
# staleness check reports the same green tick as one that verified it.
# `--require-build-checks` turns a missing artefact into a failure that names it.
#
# Two of these guards caught a real staleness in Phase 8 the moment the sidecar
# was rebuilt without the installer, so the ordering is not a formality.
#
# Check the built sidecar and installer — run AFTER a build, never before.
[group('build')]
[working-directory('apps/backend')]
verify-build: setup
    uv run pytest tests/test_sidecar_binary.py tests/test_installer_bundle.py --require-build-checks -v

# Install the produced installer on THIS machine and run the installed sidecar
# with Python scrubbed from its environment.
#
# This is §5 Phase 9's "runs on a second Windows machine with no Python
# installed", as close as one machine can state it — see CLAUDE.md's "The
# machine reality" for why the literal form is unavailable. In CI it runs on a
# fresh windows-latest runner against the artefact the build job uploaded, which
# is a different machine from any developer's and the exact bytes a user gets.
#
# It installs software, so it is not part of `just test` and never will be.
# `AGENTSPACE_INSTALLER_DIR` points it at an installer somewhere other than the
# local bundle directory.
#
# Install the built installer here and run it with no Python on PATH.
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
