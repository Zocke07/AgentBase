# AgentSpace

A local-first desktop application where multiple AI agents collaborate on a task
and you watch them work in real time on a live graph.

Everything runs on your machine — orchestration, tool execution, and state.
The only traffic that leaves it is model inference.

**Status: Phase 11 of 11 done; Phase 10's portfolio pass remains.** The
application works end to end: you define a *space* — a roster of agents, a
folder they may touch, and the rules their runs are held to — a supervisor
delegates to that roster, every filesystem, shell and network call stops at an
approval gate, and the whole run is watchable live on a graph, in plain
language, from the window or from Discord. See [BUILD_SPEC.md](BUILD_SPEC.md)
for the full design and phase plan, and [CLAUDE.md](CLAUDE.md) for what each
phase actually verified.

## Development

Requires [`just`](https://just.systems), [`uv`](https://docs.astral.sh/uv/),
Node (see `.nvmrc`), and — from Phase 1 onward — the Rust MSVC toolchain plus
the Visual Studio C++ build tools. Python 3.12 is fetched by `uv`.

The **[Developer Guide](docs/DEVELOPER_GUIDE.md)** covers the rest: the three
ways to run the app from source, how to debug each half, how the tests are
built, and the checklists for adding an event type, a setting, a secret, a
migration, a tool or a provider without tripping a guard.

```
just setup   # install dependencies
just check   # lint + typecheck
just ci      # lint + typecheck + test
just paths   # where generated files go
```

Everything this repository generates stays inside it — build output, virtual
environment, `node_modules`, and the package caches for cargo, uv and npm, which
the justfile redirects into a git-ignored `.dev/`. Nothing is written to your
home directory or system drive except the tool installations themselves. Run
`just paths` to see the resolved locations, `just clean-dev` to drop the caches,
or `just clean` to remove every git-ignored file.

### Building the Windows installer

```
just build-sidecar     # freeze the FastAPI sidecar with PyInstaller
just build-installer   # rebuild the sidecar, then bundle it
just verify-build      # check the built artefacts, refusing to skip
```

The installer lands in
`apps/desktop/src-tauri/target/release/bundle/nsis/`. It installs per-user, so
it needs no administrator rights, and it embeds the WebView2 bootstrapper so it
works on machines that lack the runtime.

Run `just verify-build` *after* a build, never before: it launches the frozen
binary, unpacks the produced installer and compares the sidecar inside it
against the one just built. Those checks skip when nothing is built — which is
right for `just test` and wrong for a release, so this recipe passes
`--require-build-checks` and a missing artefact fails instead of skipping.

## Installing

Download `AgentSpace_<version>_x64-setup.exe` from the
[latest release](../../releases/latest), or from the artefacts of any green
[build run](../../actions/workflows/build.yml). Every release has been installed
and run by CI on a clean Windows machine with Python removed from its
environment before it was published.

**The build is unsigned, so Windows will warn you once.** SmartScreen shows
*"Windows protected your PC"* — click **More info**, then **Run anyway**. That is
the whole of it: there is no terminal command to run and no setting to change,
and it does not reappear after the first time. Signing the installer with an EV
certificate would remove the prompt; it costs real money and buys nothing else,
so it is deliberately skipped.

The installer needs no administrator rights and installs for the current user
only. Your data — the event log, agent definitions and one folder per space
under `spaces\` — lives in `%LOCALAPPDATA%\dev.agentspace.desktop`, outside the
installation, so upgrading or uninstalling the app does not touch it. An install
from before spaces existed keeps its files: the old `workspace` folder becomes
the default space's folder on the first launch.

Once it is installed, the **[User Guide](docs/USER_GUIDE.md)** covers everything
after the first launch: adding an API key or using a local model, changing
settings, starting a run, answering approvals, defining agents, and connecting
Discord. Keys and settings are entered on the app's **Settings** tab; a key is
written to the operating system's keychain and read the next time the app
starts, so set it, then restart.

## CI

[`.github/workflows/build.yml`](.github/workflows/build.yml) runs the test job
before the build job and gates it: lint, typecheck and both test suites must
pass on Windows *and* macOS before any installer is bundled. A red test leaves
the build job skipped rather than producing an artefact nobody should download.

macOS is built and deliberately not published — it exists to catch
cross-platform breakage continuously, so an eventual Mac release is a flag flip
rather than a port. It earned that on its first run, with a type error that no
Windows run could see. `just typecheck` now runs `mypy --platform darwin` too,
so that class of failure is caught before a push.

A proper README — screenshot, one-command demo, architecture diagram — is
Phase 10.
