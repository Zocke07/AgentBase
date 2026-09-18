# Checklists

## Adding things

Each of these is a set of places that must agree. In every case a test already
exists that fails when they do not: read the failure, it names the other place.

### An event type

1. `events/types.py`: add to `EventType`; add to `TERMINAL_RUN_EVENTS` if it
   ends a run.
2. `just schemas`: regenerate `packages/schemas`. `test_openapi_snapshot.py`
   fails byte-for-byte until you do.
3. `apps/desktop/src/state/reducer.ts`: a `case` for it. Update `state/describe.ts`
   for its plain-language sentence, and `EventLog.tsx` if it needs rendering.
4. `channels/render.py`: a `case` in `fold`. The `case _: assert_never(...)`
   arm makes this a **mypy error**, not a runtime surprise;
   `test_every_event_type_in_the_contract_is_handled_by_the_fold` also checks.
5. Same commit for all of it (BUILD_SPEC §4).

### A workspace setting

1. `store/settings.py`: a field on `WorkspaceSettings` with its default.
2. `api/settings.py`: the same field on `UpdateSettingsRequest`.
   `test_every_workspace_setting_can_be_patched` compares the two field sets;
   `extra="forbid"` already makes a missing one a loud 422.
3. `just schemas`.
4. If a run depends on it, **snapshot it at run start** (see `RunLimits`): a
   run must not be held to different rules at step 1 and step 12.
5. If a service depends on it (channels), make the `PATCH` handler reconcile
   immediately. The **Restart AgentSpace** button exists for keys, which only
   reach the sidecar at spawn; a setting must never need it.
6. For a space override, also update `store/spaces.py`, `api/spaces.py`,
   `Space.apply_to`, and the space editor. Preserve the distinction between a
   missing PATCH field, `null` for inheritance, and `[]` for a space's manual
   approval policy. Check `test_spaces_run.py` for snapshot and isolation tests.

**Never default a value elsewhere that duplicates a setting the user can
change.** That was the Phase 5 `max_steps` bug; the rule is in CLAUDE.md.

### A secret

1. `secrets.py`: `SECRET_KEYS`.
2. `apps/desktop/src-tauri/src/lib.rs`: `SECRET_NAMES`. `test_secrets.py` compares them.
3. If it is a provider key, `providers/factory.py`: `SUPPORTED_PROVIDERS`.
4. `apps/desktop/src/components/SettingsView.tsx`: the key row. The app reads
   keys at startup, so saving or clearing a key requires a restart; the
   `KeyRows` component offers it through the shell's `restart_app` once any
   key has changed.

Secrets go in the keychain and travel over stdin. Never in `settings`, never in
a file, never in `argv`, never in a log. `test_no_api_keys_in_tracked_files`
scans for key-shaped prefixes, including in Markdown.

### A migration

1. `store/NNN_name.sql`: additive if at all possible. Guard any `UPDATE` to a
   seeded row on it still holding its seeded value (see 004).
2. `store/db.py`: append to `MIGRATION_FILES`.
3. Nothing else: the PyInstaller `--add-data` glob is `*.sql`, and
   `test_every_migration_file_is_bundled_by_the_packaging_glob` confirms it.
4. Run the relevant upgrade-preservation tests in `test_store_db.py` and
   `test_store_spaces.py` against populated old schemas. Also start the sidecar
   with a separate temporary data directory to check a fresh install.

Built-ins are seeded by migration 003, **not** by startup code: a migration
runs exactly once, so it does not overwrite later user edits. Space creation
and the explicit seed endpoint use `store/builtins.py` through `AgentDefStore`;
these copies have fresh ids and are deletable. Keep those seed definitions and
the migration's defaults consistent.

### A tool

1. `tools/catalogue.py`: a `ToolDeclaration` with a name, description and
   `RiskLevel`. This is what `allowed_tools` validates against and what the
   editor's checkboxes render. Policy is a *set* of levels, not a threshold.
2. `tools/builtin/<module>.py`: implement `Tool`: **`prepare`** resolves and
   validates while touching nothing (the sandbox check lives here, so an
   out-of-bounds call is refused before anyone is asked), **`execute`** carries
   out an already-approved call. `Prepared.summary` is the sentence the user
   reads; build it from the *resolved* call.
3. `tools/builtin/__init__.py`: add to `BUILTIN_TOOLS`. `GET /tools` then
   reports it `available: true`.

Every tool goes through the gate. There is no flag to skip it and there must
not be one (§1 constraint 5).

### A model or a provider

- **Model:** a row in the appropriate provider table in `providers/pricing.py`,
  from which `PRICES` and `MODELS_BY_PROVIDER` are derived, as dollar *strings*
  (`_usd("2.50", "10.00")`): never a float near money. It appears in
  `GET /settings/providers` and the editor dropdown automatically. An unpriced
  model is refused, not charged at zero; that is the point.
- **Provider:** a class implementing `Provider` (both `complete` and
  `stream`) in `providers/`, an entry in `factory.SUPPORTED_PROVIDERS`, and
  a construction branch in `build_provider`, a model catalogue entry, and
  `qualified_model` if it namespaces model ids the way Ollama does.
  `test_qualified_model_is_what_the_built_provider_reports` covers every
  provider.

### An API route

1. A router in `api/`, included in `main.create_app`.
2. `just schemas`. The emitter **raises** on any OpenAPI keyword it does not
   understand rather than emitting `unknown`: fix the model or extend
   `openapi.py`, do not weaken the emitter.
3. If the dashboard calls it, `lib/api.ts`: using only generated types.
   `test_the_schema_covers_every_route_the_dashboard_calls` checks.
4. Validation and lookup failures are `400`/`404`/`409`/`422` with a readable message and, where
   possible, the `field` they blame. Never a 500.

---
