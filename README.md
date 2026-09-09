# AgentSpace

A local-first desktop application where multiple AI agents collaborate on a task
and you watch them work in real time on a live graph.

Everything runs on your machine — orchestration, tool execution, and state.
The only traffic that leaves it is model inference.

**Status: Phase 0 of 10 (scaffold).** Not yet runnable. See
[BUILD_SPEC.md](BUILD_SPEC.md) for the full design and phase plan, and
[CLAUDE.md](CLAUDE.md) for current progress.

## Development

Requires [`just`](https://just.systems), [`uv`](https://docs.astral.sh/uv/),
Node (see `.nvmrc`), and — from Phase 1 onward — the Rust MSVC toolchain plus
the Visual Studio C++ build tools. Python 3.12 is fetched by `uv`.

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

A proper README — screenshot, one-command demo, architecture diagram — is
Phase 10.
