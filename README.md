# AgentSpace

A local-first desktop application where multiple AI agents collaborate on a task
and you watch them work in real time on a live graph.

Everything runs on your machine — orchestration, tool execution, and state.
The only traffic that leaves it is model inference.

**Status: Phase 0 of 10 (scaffold).** Not yet runnable. See
[BUILD_SPEC.md](BUILD_SPEC.md) for the full design and phase plan, and
[CLAUDE.md](CLAUDE.md) for current progress.

## Development

Requires [`just`](https://just.systems), [`uv`](https://docs.astral.sh/uv/), and
Node (see `.nvmrc`). Python 3.12 is fetched by `uv`.

```
just setup   # install dependencies
just check   # lint + typecheck
just ci      # lint + typecheck + test
```

A proper README — screenshot, one-command demo, architecture diagram — is
Phase 10.
