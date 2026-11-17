# AgentBase

A local-first desktop app where AI agents collaborate on a task while you watch
their work on a live graph.

Orchestration, tool execution, and state remain on your machine. Cloud models
receive prompts and tool results; the web tool can contact public sites; and
the optional Discord connection sends run updates.

**Status: the application works end to end.** You define a *space*: a roster of
agents, a folder they may touch, and rules governing its runs. A supervisor
then delegates to that roster. Every filesystem, shell, and network call pauses at
an approval gate, and you can watch the run live on a graph, in plain language,
from the app or Discord. Each space is also a local Markdown knowledge vault
with links, backlinks, properties, graph search, automatic cited RAG, and
durable cross-run memory. You can open it directly in Obsidian, but Obsidian is
optional. See
[BUILD_SPEC.md](BUILD_SPEC.md) for the full design and [CLAUDE.md](CLAUDE.md)
for the current implementation context.

## Development

Requires [`just`](https://just.systems), [`uv`](https://docs.astral.sh/uv/),
Node (see `.nvmrc`), and (from Phase 1 onward) the Rust MSVC toolchain plus
the Visual Studio C++ build tools. Python 3.12 is fetched by `uv`.

The **[Developer Guide](docs/developer_guide/README.md)** covers three ways to
run the app from source, debugging, tests, and checklists for adding an event
type, setting, secret, migration, tool, or provider without tripping a guard.

```
just setup   # install dependencies
just check   # lint + typecheck
just ci      # lint + typecheck + test
just paths   # where generated files go
```

Project build output, the virtual environment, `node_modules`, and Cargo, uv,
and npm caches stay in this repository. The justfile redirects them to
git-ignored locations. Toolchains and Tauri's small platform-tool cache use
their normal system locations. Run `just paths` to see project paths,
`just clean-dev` to drop caches, or `just clean` to remove every git-ignored
file.

### Building a release bundle

```
just build-sidecar     # freeze the FastAPI sidecar with PyInstaller
just build-installer   # rebuild the sidecar, then bundle it
just verify-build      # check the built artefacts, refusing to skip
```

The Windows installer lands in
`apps/desktop/src-tauri/target/release/bundle/nsis/`. On macOS, the `.app`
lands under `bundle/macos/` and the distributable disk image, with the app
beside an Applications link, under `bundle/dmg/`.

Run `just verify-build` *after* a build, never before: it launches the frozen
binary, unpacks the installer, and compares its sidecar with the one just
built. These checks skip when nothing is built (right for `just test`, wrong
for a release), so this recipe passes `--require-build-checks`; a missing
artefact fails instead of skipping.

## Installing

Download `AgentBase_0.5.0_x64-setup.exe` for Windows x64 or
`AgentBase_0.5.0_aarch64.dmg` for Apple Silicon macOS from the
[latest release](https://github.com/Zocke07/AgentBase/releases/latest) or a green
[build run](https://github.com/Zocke07/AgentBase/actions/workflows/build.yml).
See the [User Guide](docs/user_guide/1_getting_started.md) for both installation
paths.

**The Windows installer is unsigned.** SmartScreen can show
*"Windows protected your PC"*: click **More info**, then **Run anyway** if you
trust the download. A new build or machine policy can show the warning again.

The installer needs no administrator rights and installs only for the current
user. Your data, including the event log, agent definitions, and one folder per
space under `spaces\`, lives outside the installation in
`%LOCALAPPDATA%\dev.agentbase.desktop`, so upgrades and uninstalls leave it
alone. An installation from before spaces existed keeps its files: the old
`workspace` folder becomes the default space's folder on first launch.

AgentBase also adopts data from a pre-rename installation when its new data
directory is empty. Keep the earlier app closed during that first launch. New
AgentBase credentials take precedence, while existing credentials remain
available until you replace or remove them in **Settings > Keys**.

The new identifier means this is a separate app, not an in-place upgrade of
AgentSpace: Windows lists it as its own entry in **Apps & features** and
macOS installs it as its own `AgentBase.app` alongside the old one. Once
you have confirmed your data carried over, uninstall or delete the old
AgentSpace app yourself; AgentBase does not touch it.

Once installed, the **[User Guide](docs/user_guide/README.md)** covers API-key
or ChatGPT-subscription connections, local models, settings, runs, approvals,
agents, and Discord. Credentials stay in the operating system's credential
store. Enter API keys under **Settings > Keys**; the app reads them on its next
start.

## CI

[`.github/workflows/build.yml`](.github/workflows/build.yml) runs lint,
typecheck, and both test suites on Windows *and* macOS before bundling an
installer. A failed test skips the build job rather than producing an artefact
nobody should download.

CI uploads and publishes both the Windows installer and an ad-hoc signed,
unnotarized Apple Silicon macOS disk image. The image is mounted and verified
after the build, including a strict signature check of the app it carries.
`just typecheck` runs mypy for the host and the other
supported platform so platform-specific branches are checked before a push.
