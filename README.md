# AgentSpace

A local-first desktop application where multiple AI agents collaborate on a task
and you watch them work in real time on a live graph.

Orchestration, tool execution, and state stay on your machine. Cloud models
receive prompts and tool results, the web tool can contact public sites, and
the optional Discord connection sends run updates to Discord.

**Status: the application works end to end.** You define a *space* (a roster
of agents, a folder they may touch, and the rules their runs are held to), a
supervisor delegates to that roster, every filesystem, shell and network call
stops at an approval gate, and the whole run is watchable live on a graph, in
plain language, from the window or from Discord. See
[BUILD_SPEC.md](BUILD_SPEC.md) for the full design and [CLAUDE.md](CLAUDE.md)
for the current implementation context.

## Development

Requires [`just`](https://just.systems), [`uv`](https://docs.astral.sh/uv/),
Node (see `.nvmrc`), and (from Phase 1 onward) the Rust MSVC toolchain plus
the Visual Studio C++ build tools. Python 3.12 is fetched by `uv`.

The **[Developer Guide](docs/developer_guide/README.md)** covers the rest: the three
ways to run the app from source, how to debug each half, how the tests are
built, and the checklists for adding an event type, a setting, a secret, a
migration, a tool or a provider without tripping a guard.

```
just setup   # install dependencies
just check   # lint + typecheck
just ci      # lint + typecheck + test
just paths   # where generated files go
```

Project build output, the virtual environment, `node_modules`, and the cargo,
uv and npm package caches stay in this repository. The justfile redirects them
into git-ignored locations. Toolchains and Tauri's own small platform-tool cache
use their normal system locations. Run `just paths` to see the project paths,
`just clean-dev` to drop its caches, or `just clean` to remove every
git-ignored file.

### Building a release bundle

```
just build-sidecar     # freeze the FastAPI sidecar with PyInstaller
just build-installer   # rebuild the sidecar, then bundle it
just verify-build      # check the built artefacts, refusing to skip
```

The Windows installer lands in
`apps/desktop/src-tauri/target/release/bundle/nsis/`. On macOS, the `.app`
lands under `bundle/macos/`; run `just package-macos` before verification to
create the distributable archive without losing executable permissions.

Run `just verify-build` *after* a build, never before: it launches the frozen
binary, unpacks the produced installer and compares the sidecar inside it
against the one just built. Those checks skip when nothing is built, which is
right for `just test` and wrong for a release, so this recipe passes
`--require-build-checks` and a missing artefact fails instead of skipping.

## Installing

Download `AgentSpace_0.2.0_x64-setup.exe` for Windows x64 or
`AgentSpace_0.2.0_aarch64-apple-darwin.app.zip` for Apple Silicon macOS from the
[latest release](https://github.com/Zocke07/AgentBase/releases/latest), once
0.2.0 is published, or from the artifacts of a green
[build run](https://github.com/Zocke07/AgentBase/actions/workflows/build.yml). See the
[User Guide](docs/user_guide/1_getting_started.md) for both installation paths.

**The Windows installer is unsigned.** SmartScreen can show
*"Windows protected your PC"*: click **More info**, then **Run anyway** if you
trust the download. A new build or machine policy can show the warning again.

The installer needs no administrator rights and installs for the current user
only. Your data (the event log, agent definitions and one folder per space
under `spaces\`) lives in `%LOCALAPPDATA%\dev.agentspace.desktop`, outside the
installation, so upgrading or uninstalling the app does not touch it. An install
from before spaces existed keeps its files: the old `workspace` folder becomes
the default space's folder on the first launch.

Once it is installed, the **[User Guide](docs/user_guide/README.md)** covers everything
after the first launch: adding an API key or using a local model, changing
settings, starting a run, answering approvals, defining agents, and connecting
Discord. Keys are entered under **Settings > Keys**, written to the operating
system's credential store, and read the next time the app starts.

## CI

[`.github/workflows/build.yml`](.github/workflows/build.yml) runs the test job
before the build job and gates it: lint, typecheck and both test suites must
pass on Windows *and* macOS before any installer is bundled. A red test leaves
the build job skipped rather than producing an artefact nobody should download.

From 0.2.0, CI uploads and publishes both the Windows installer and an unsigned,
unnotarized Apple Silicon macOS app archive. The macOS archive is made with
`ditto` before artifact upload and verified after extraction. `just typecheck`
runs mypy for the host and the other supported platform so platform-specific
branches are checked before a push.
