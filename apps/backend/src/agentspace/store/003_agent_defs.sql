-- Migration 003 - agent definitions (BUILD_SPEC §4, §5 Phase 5).
--
-- `agent_defs` is §4 verbatim. This is the migration that turns agents from
-- hardcoded Python classes into editable data: from here on `registry.py`
-- constructs workers from these rows rather than importing a class per role.
--
-- **The built-ins are seeded here rather than on first launch in code.**
-- §5 Phase 5 asks for 3-4 definitions seeded "on first launch" so a fresh
-- install is usable immediately, and the obvious implementation is a startup
-- check - "are there any built-in rows? if not, insert them". That check is
-- wrong the first time a user edits a built-in and then upgrades: any
-- re-seeding logic has to distinguish "never seeded" from "seeded and since
-- edited", and getting it wrong silently reverts the user's edit. A migration
-- runs exactly once by construction, so the question never arises.
--
-- The ids are fixed uuid4 literals rather than generated per install. §4 says
-- uuid4 and these are; pinning them means "the built-in researcher" is the
-- same identity on every machine, so an exported run or a bug report can name
-- one unambiguously.
--
-- Every seeded definition has an empty `allowed_tools`. That is not a
-- placeholder: §5 Phase 5 says "an empty array means the agent can reason and
-- hand off but touches nothing", which is exactly the truth in this phase -
-- no tool is implemented until Phase 6's approval gate exists, so an agent
-- seeded with `write_file` would spend a step discovering it cannot use it.
-- Phase 6 widens these rows when there is something for them to point at.

CREATE TABLE agent_defs (
  id            TEXT PRIMARY KEY,        -- uuid4
  name          TEXT NOT NULL UNIQUE,    -- display name, referenced in handoffs
  role          TEXT NOT NULL,           -- one-line description shown in the UI
  system_prompt TEXT NOT NULL,
  provider      TEXT,                    -- NULL = inherit workspace default
  model         TEXT,                    -- NULL = inherit workspace default
  allowed_tools TEXT NOT NULL,           -- JSON array of tool names
  max_steps     INTEGER NOT NULL DEFAULT 20,
  auto_approve  TEXT NOT NULL DEFAULT '[]',  -- JSON array of risk levels, see §5 Phase 6
  is_builtin    INTEGER NOT NULL DEFAULT 0,  -- seeded defaults, editable but not deletable
  enabled       INTEGER NOT NULL DEFAULT 1,
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);

-- The roster is read by name on every spawn, and listed by the Phase 7 editor.
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
