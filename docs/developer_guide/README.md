# AgentBase: Developer Guide

This guide is for the person changing the code. If you just want to run the
app, see the [User Guide](../user_guide/README.md).

Read these alongside the guide:

- **[BUILD_SPEC.md](../../BUILD_SPEC.md)** is the design and the constraints. Read
  it first. If you are touching the core loop or the Tauri shell, a constraint
  applies.
- **[CLAUDE.md](../../CLAUDE.md)** holds current project context and working rules.
- **[Project history](../history/README.md)** preserves previous sessions' decisions,
  verification results and unresolved observations.
- **[User Guide](../user_guide/README.md)** is how the product behaves from the outside.

---


## Contents

1. [Architecture](1_architecture.md)
   - The code layout
   - Event projections and space boundaries
   - Conventions
   - Gotchas
2. [Development Setup](2_development_setup.md)
   - Toolchain
   - Running it
   - The dev data directory
3. [Debugging](3_debugging.md)
   - Debugging the backend
   - Debugging the UI
   - Debugging the Tauri shell
4. [Testing and CI](4_testing_and_ci.md)
   - Tests
   - CI
5. [Checklists](5_checklists.md)
   - Adding things
6. [Packaging](6_packaging.md)
   - Building and verifying the installer
