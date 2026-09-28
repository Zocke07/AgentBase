-- Migration 003 - agent definitions (BUILD_SPEC §4, §5 Phase 5).
--
-- `agent_defs` is §4 verbatim. `registry.py` now builds editable workers from
-- rows instead of importing one class per role.
--
-- Seed built-ins in this one-time migration, not at startup: re-seeding cannot
-- safely distinguish a missing row from a user-edited one.
--
-- Fixed UUID4 literals give each built-in the same identity on every machine,
-- so exports and bug reports identify it unambiguously.
--
-- Seed empty `allowed_tools`: Phase 5 permits reasoning and handoffs only until
-- Phase 6 implements and grants tools.

CREATE TABLE agent_defs (
  id            TEXT PRIMARY KEY,        -- uuid4
  name          TEXT NOT NULL UNIQUE,    -- display name used in handoffs
  role          TEXT NOT NULL,           -- one-line description shown in the UI
  system_prompt TEXT NOT NULL,
  provider      TEXT,                    -- NULL inherits workspace default
  model         TEXT,                    -- NULL inherits workspace default
  allowed_tools TEXT NOT NULL,           -- JSON array of tool names
  max_steps     INTEGER NOT NULL DEFAULT 20,
  auto_approve  TEXT NOT NULL DEFAULT '[]',  -- JSON risk-level array; §5 Phase 6
  is_builtin    INTEGER NOT NULL DEFAULT 0,  -- editable seeded default; not deletable
  enabled       INTEGER NOT NULL DEFAULT 1,
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);

-- Spawning resolves names; the Phase 7 editor lists this roster.
CREATE INDEX idx_agent_defs_enabled ON agent_defs(enabled);

INSERT INTO agent_defs
  (id, name, role, system_prompt, allowed_tools, max_steps, is_builtin, created_at, updated_at)
VALUES
  (
    'b6a1f0d2-8c34-4e59-9f27-1a5d3c7e40b1',
    'researcher',
    'Gathers facts and figures, and reports them without embellishment',
    'You are a researcher. Establish the facts you have been asked for and '
      || 'report them plainly, with figures where figures exist. State what you '
      || 'do not know rather than filling the gap. Do not write prose for '
      || 'publication: another agent does that with what you find.',
    '[]', 20, 1, strftime('%Y-%m-%dT%H:%M:%S+00:00','now'), strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
  ),
  (
    'd41b7e58-2f96-4a03-8b6c-9e2d5a1f7c34',
    'writer',
    'Turns findings into clear prose for the reader',
    'You are a writer. Turn what you have been given into clear, concrete '
      || 'prose for a reader who was not present for the research. Keep the '
      || 'figures exactly as they were given to you: do not round them, and do '
      || 'not add any you were not given. Be brief.',
    '[]', 20, 1, strftime('%Y-%m-%dT%H:%M:%S+00:00','now'), strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
  ),
  (
    'f0927c14-6b8d-4e71-a53f-2c9814d6b0ae',
    'reviewer',
    'Checks work against the task it was meant to do, and says what is wrong',
    'You are a reviewer. Check the work you have been given against the task '
      || 'it was meant to accomplish. Report specific problems and what would '
      || 'fix them. If it is sound, say so plainly rather than inventing '
      || 'criticism. Do not rewrite it yourself.',
    '[]', 20, 1, strftime('%Y-%m-%dT%H:%M:%S+00:00','now'), strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
  );
