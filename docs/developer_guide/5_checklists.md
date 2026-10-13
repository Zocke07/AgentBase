# Checklists

## Adding things

Each checklist names locations that must agree. A test fails when they diverge;
read its failure to find the other location.

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
   `test_every_workspace_setting_can_be_patched` compares their field sets;
   `extra="forbid"` makes a missing field a loud 422.
3. `just schemas`.
4. If a run depends on it, **snapshot it at run start** (see `RunLimits`): a
   run must not be held to different rules at step 1 and step 12.
5. For dependent services (channels), reconcile in the `PATCH` handler.
   **Restart AgentBase** is only for keys, which reach the sidecar at spawn;
   settings must never need it.
6. For a space override, also update `store/spaces.py`, `api/spaces.py`,
   `Space.apply_to`, and the space editor. Preserve the distinction between a
   missing PATCH field, `null` for inheritance, and `[]` for manual space
   approval. Check `test_spaces_run.py` for snapshot/isolation tests.

**Never duplicate a user-changeable setting's default.** Phase 5's `max_steps`
bug established this CLAUDE.md rule.

### A secret

1. `secrets.py`: `SECRET_KEYS`.
2. `apps/desktop/src-tauri/src/lib.rs`: `SECRET_NAMES`. `test_secrets.py` compares them.
3. If it is a provider key, `providers/factory.py`: `SUPPORTED_PROVIDERS`.
4. `apps/desktop/src/components/SettingsView.tsx`: the key row. The app reads
   keys at startup, so saving or clearing a key requires a restart; the
   `KeyRows` component offers it through the shell's `restart_app` once any
   key has changed.

Secrets live in the keychain and travel over stdin, never `settings`, files,
`argv`, or logs. `test_no_api_keys_in_tracked_files` scans key-like prefixes,
including Markdown.

### A migration

1. `store/NNN_name.sql`: additive if at all possible. Guard any `UPDATE` to a
   seeded row on it still holding its seeded value (see 004).
2. `store/db.py`: append to `MIGRATION_FILES`.
3. Nothing else: the PyInstaller `--add-data` glob is `*.sql`, and
   `test_every_migration_file_is_bundled_by_the_packaging_glob` confirms it.
4. Run the relevant upgrade-preservation tests in `test_store_db.py` and
   `test_store_spaces.py` against populated old schemas. Also start the sidecar
   with a separate temporary data directory to check a fresh install.

Seed built-ins in migrations, **not** startup: migrations run once and cannot
overwrite later edits. Migration 010 seeds ten fixed-ID, `is_builtin = 1`
investment definitions in the default space, skipping names the user already
has. It retires 003's three generic roles only while each retains exact shipped
values; otherwise it remains deletable. Space creation and the explicit seed
endpoint copy `store/builtins.py` starter roles through `AgentDefStore`; copies
have new IDs, are deletable, and now exist only in Python.

### A tool

1. `tools/catalogue.py`: a named, described `ToolDeclaration` with `RiskLevel`.
   `allowed_tools` validates it and editor checkboxes render it. Policy is a
   *set* of levels, not a threshold. Set `default_space_only=True` for a tool
   built for the default space's investment pipeline: other spaces are then
   neither offered nor permitted it, and its agents cannot leave the default
   space (BUILD_SPEC, "The investment pipeline stays in the default space").
2. `tools/builtin/<module>.py`: implement `Tool`: **`prepare`** resolves and
   validates without side effects (including sandbox refusal before approval);
   **`execute`** performs the approved call. Build user-facing `Prepared.summary`
   from the *resolved* call.
3. `tools/builtin/__init__.py`: add to `BUILTIN_TOOLS`. `GET /tools` then
   reports it `available: true`.

Every tool passes the gate; no bypass flag may exist (§1 constraint 5). A
policy answer is a gate decision, recorded like any other, and is the only
way a call runs without a person. A network tool must put the host it will
reach in `Prepared.payload["host"]`, or the host list cannot bound it; a tool
that writes must resolve through `Sandbox.resolve_write_path`. A new high-risk
tool is never answerable by policy (`POLICY_LEVELS`).

### A default setting

`SettingsStore` persists only saved keys, so changing a `DEFAULT_*` constant
changes every install that never saved that key. Ship a migration that writes
the old value into databases that have been used, as 018 does, and test both
a fresh and an upgraded database.

### A model or a provider

- **Model:** add a dollar-*string* row (`_usd("2.50", "10.00")`, never float)
  to its `providers/pricing.py` table; it derives `PRICES` and
  `MODELS_BY_PROVIDER`, then appears in `GET /settings/providers` and the
  editor. Refuse unpriced models rather than charging zero.
- **Provider:** a class implementing `Provider` (both `complete` and
  `stream`) in `providers/`, an entry in `factory.SUPPORTED_PROVIDERS`, and
  a construction branch in `build_provider`, a model catalogue entry, and
  `qualified_model` if it namespaces model ids the way Ollama does.
  `test_qualified_model_is_what_the_built_provider_reports` covers each one.
  The adapter must resend an assistant turn's `Message.tool_calls` in the
  vendor's own call shape and link each `Role.TOOL` result to its call. A
  history that dropped the calls made results look unrequested, and models
  repeated calls already answered until the stuck guard stopped them.

### An API route

1. A router in `api/`, included in `main.create_app`.
2. `just schemas`. The emitter **raises** on any OpenAPI keyword it does not
   understand rather than emitting `unknown`: fix the model or extend
   `openapi.py`, do not weaken the emitter.
3. If the dashboard calls it, `lib/api.ts`: using only generated types.
   `test_the_schema_covers_every_route_the_dashboard_calls` checks.
4. Return validation/lookup errors as `400`/`404`/`409`/`422` with a readable
   message and, where possible, the blamed `field`; never 500.

---
