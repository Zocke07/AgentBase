-- Migration 006 — spaces (BUILD_SPEC §5 Phase 11).
--
-- A space owns a roster, a folder and a set of rules; runs belong to the
-- space they were started in. `spaces` is the table §5 Phase 11 specifies,
-- verbatim. The folder is *not* a column: it is `<data dir>/spaces/<id>/`,
-- derived, so a row cannot name a path outside the place the application
-- owns.
--
-- **The default space has a fixed id**, like the seeded built-ins in 003, so
-- "the default space" is one identity on every machine — and so this file and
-- `store/spaces.py` can agree on it by literal rather than by lookup. Every
-- rule on it is NULL, which means "inherit the app-wide default": a database
-- upgraded by this migration behaves exactly as the single workspace did.
--
-- **Both `space_id` columns arrive by table rebuild**, not `ALTER TABLE ADD
-- COLUMN`. SQLite will not add a `REFERENCES` column with a non-NULL default
-- while foreign keys are on, and cannot add `NOT NULL` without one — so each
-- table is created again with the column, copied, dropped and renamed. That
-- needs foreign keys *off* for the duration (`DROP TABLE runs` would otherwise
-- refuse, because `events` still points at it), which is why `db.py` runs
-- this migration with the check deferred and verifies the result with
-- `PRAGMA foreign_key_check` before committing.
--
-- `agent_defs.UNIQUE(name)` becomes `UNIQUE(space_id, name)`: a name is
-- unique in its roster, which is the only place the supervisor ever resolves
-- one. Two spaces may each have a `writer`.

CREATE TABLE spaces (
  id                  TEXT PRIMARY KEY,        -- uuid4; the default space's is fixed
  name                TEXT NOT NULL UNIQUE,
  description         TEXT NOT NULL DEFAULT '',
  provider            TEXT,                    -- NULL = inherit the app-wide default
  model               TEXT,                    -- NULL = inherit
  auto_approve        TEXT,                    -- NULL = inherit; else JSON array, narrows only
  max_steps_per_agent INTEGER,                 -- NULL = inherit; a space may set these either way
  max_agents_per_run  INTEGER,
  max_run_seconds     INTEGER,
  archived            INTEGER NOT NULL DEFAULT 0,
  created_at          TEXT NOT NULL,
  updated_at          TEXT NOT NULL
);

INSERT INTO spaces (id, name, description, created_at, updated_at)
VALUES (
  '5c1e5a2e-0d4b-4c93-9a7f-3b2e8d1c6f00',
  'Main',
  '',
  strftime('%Y-%m-%dT%H:%M:%S+00:00','now'),
  strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
);

-- --- agent_defs: gains space_id, and its name is unique per space -----------

CREATE TABLE agent_defs_v6 (
  id            TEXT PRIMARY KEY,
  space_id      TEXT NOT NULL REFERENCES spaces(id),
  name          TEXT NOT NULL,
  role          TEXT NOT NULL,
  system_prompt TEXT NOT NULL,
  provider      TEXT,
  model         TEXT,
  allowed_tools TEXT NOT NULL,
  max_steps     INTEGER NOT NULL DEFAULT 20,
  auto_approve  TEXT NOT NULL DEFAULT '[]',
  is_builtin    INTEGER NOT NULL DEFAULT 0,
  enabled       INTEGER NOT NULL DEFAULT 1,
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL,
  UNIQUE(space_id, name)
);

INSERT INTO agent_defs_v6
  (id, space_id, name, role, system_prompt, provider, model, allowed_tools,
   max_steps, auto_approve, is_builtin, enabled, created_at, updated_at)
SELECT
  id, '5c1e5a2e-0d4b-4c93-9a7f-3b2e8d1c6f00', name, role, system_prompt, provider, model,
  allowed_tools, max_steps, auto_approve, is_builtin, enabled, created_at, updated_at
FROM agent_defs;

DROP TABLE agent_defs;
ALTER TABLE agent_defs_v6 RENAME TO agent_defs;

CREATE INDEX idx_agent_defs_enabled ON agent_defs(enabled);
CREATE INDEX idx_agent_defs_space ON agent_defs(space_id);

-- --- runs: gains space_id ----------------------------------------------------

CREATE TABLE runs_v6 (
  id           TEXT PRIMARY KEY,
  space_id     TEXT NOT NULL REFERENCES spaces(id),
  goal         TEXT NOT NULL,
  status       TEXT NOT NULL,
  origin       TEXT NOT NULL,
  origin_ref   TEXT,
  created_at   TEXT NOT NULL,
  finished_at  TEXT
);

INSERT INTO runs_v6 (id, space_id, goal, status, origin, origin_ref, created_at, finished_at)
SELECT id, '5c1e5a2e-0d4b-4c93-9a7f-3b2e8d1c6f00', goal, status, origin, origin_ref,
       created_at, finished_at
FROM runs;

DROP TABLE runs;
ALTER TABLE runs_v6 RENAME TO runs;

CREATE INDEX idx_runs_space ON runs(space_id);
