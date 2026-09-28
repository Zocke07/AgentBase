-- Migration 006 - spaces (BUILD_SPEC §5 Phase 11).
--
-- A space owns a roster, folder, and rules; its runs belong to it. `spaces` is
-- the §5 Phase 11 table. Derive its folder as `<data dir>/spaces/<id>/` rather
-- than store a path that could escape application-owned storage.
--
-- The fixed default-space ID, like the 003 built-in IDs, is stable across
-- machines and matches `store/spaces.py`. Its NULL rules inherit app-wide
-- defaults, preserving single-workspace behavior after upgrade.
--
-- Rebuild, rather than `ALTER TABLE ADD COLUMN`, to add non-NULL referenced
-- `space_id` columns: SQLite cannot add one with foreign keys enabled. Disable
-- checks while copying, dropping, and renaming (`events` references `runs`);
-- `db.py` defers checks and runs `PRAGMA foreign_key_check` before commit.
--
-- Replace `agent_defs.UNIQUE(name)` with `UNIQUE(space_id, name)`: supervisors
-- resolve names within a roster, so multiple spaces may have a `writer`.

CREATE TABLE spaces (
  id                  TEXT PRIMARY KEY,        -- UUID4; default-space ID is fixed
  name                TEXT NOT NULL UNIQUE,
  description         TEXT NOT NULL DEFAULT '',
  provider            TEXT,                    -- NULL inherits app-wide default
  model               TEXT,                    -- NULL inherits
  auto_approve        TEXT,                    -- NULL inherits; JSON array only narrows
  max_steps_per_agent INTEGER,                 -- NULL inherits
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

-- --- agent_defs: add space_id; make names unique per space ------------------

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

-- --- runs: add space_id ------------------------------------------------------

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
