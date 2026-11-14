# AgentBase: Developer Guide

For code changes. To run the app, see the [User Guide](../user_guide/README.md).

Read these alongside the guide:

- **[BUILD_SPEC.md](../../BUILD_SPEC.md)** defines the design and constraints; read it
  first, especially before changing the core loop or Tauri shell.
- **[CLAUDE.md](../../CLAUDE.md)** has current project context and working rules.
- **[Project history](../history/README.md)** records decisions, verification, and
  unresolved observations.
- **[User Guide](../user_guide/README.md)** describes product behavior.

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
7. [Design system](7_design_system.md)
   - Colour, type and the parts to reuse
   - Native details and motion
   - Seeing and testing it
8. [The office](8_the_office.md)
   - How a run becomes a room
   - The rules that keep it honest
   - The office beyond the run
