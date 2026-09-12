-- Migration 004 - the approval gate's durable half (BUILD_SPEC §4, §5 Phase 6).
--
-- `approvals` is §4 verbatim. It is the last of the five tables §4 specifies,
-- and it arrives in the phase that uses it, per the rule migration 001 set:
-- a table created before anything writes to it is untested machinery whose
-- first real exercise happens on a user's machine.
--
-- **Why the row exists at all, when the waiting happens in memory.** The gate
-- blocks an agent on an `asyncio.Future`, and a future is not a fact anyone
-- can read afterwards. §2 says the event log is the authority and the UI is a
-- projection of it, so the *decision* travels as `approval.requested` and
-- `approval.resolved` events. This table is not a second copy of that history -
-- it is the index the Phase 7 dialog and `POST /approvals/{id}` need to answer
-- "which approvals are outstanding right now", which is a question about
-- current state rather than about what happened, and which scanning the whole
-- event log to answer would be the wrong shape.
--
-- **`status` includes `expired`, and that is load-bearing.** A pending
-- approval's waiter is an in-process future. A sidecar restart destroys every
-- one of them, so a row left `pending` across a restart can never be resolved
-- by anybody - the HTTP handler would find the row, resolve it, and set no
-- future. `ApprovalStore.expire_orphaned_pending` therefore runs at startup
-- and closes them out, which is why the status exists rather than being an
-- unused fourth value copied out of the spec.

CREATE TABLE approvals (
  id          TEXT PRIMARY KEY,           -- uuid4
  run_id      TEXT NOT NULL REFERENCES runs(id),
  tool        TEXT NOT NULL,
  args        TEXT NOT NULL,              -- JSON
  risk        TEXT NOT NULL,              -- low|medium|high
  status      TEXT NOT NULL,              -- pending|approved|denied|expired
  created_at  TEXT NOT NULL,
  resolved_at TEXT
);

-- The two queries that exist: "what is outstanding for this run" (the Phase 7
-- dialog, and the startup sweep) and "resolve this id" (the primary key).
CREATE INDEX idx_approvals_run_status ON approvals(run_id, status);

-- Widen the seeded built-ins now that the tools they would point at exist.
--
-- Migration 003 seeded every built-in with an empty `allowed_tools`, which was
-- the honest value while no tool was implemented: §5 Phase 5 says an empty
-- array means the agent "can reason and hand off but touches nothing", and an
-- agent seeded with `write_file` would have spent a step discovering it could
-- not use it. That is no longer true, so a fresh install should be usable with
-- the tools §5 Phase 5 asks the built-ins to make immediately available.
--
-- **Guarded on the row still holding its seeded value.** A migration runs
-- exactly once, but it runs on databases where the user has already edited
-- these rows, and silently overwriting an edit is the failure mode migration
-- 003's own comment warns about. `allowed_tools = '[]'` restricts this to rows
-- nobody has touched. The one case it cannot distinguish is a user who
-- deliberately emptied a built-in's allowlist; they get the default back once,
-- and can empty it again. That is the smaller harm than a researcher which
-- can read nothing on every fresh install.
--
-- No `auto_approve` is granted to any of them. §5 Phase 6's default is
-- manual-approve-everything, and a built-in that pre-authorized its own calls
-- would be the definition escalating its own privileges - the exact shape §5
-- Phase 5's security note says to stop on.
UPDATE agent_defs
   SET allowed_tools = '["read_file","list_dir"]',
       updated_at    = strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
 WHERE id = 'b6a1f0d2-8c34-4e59-9f27-1a5d3c7e40b1'
   AND allowed_tools = '[]';

UPDATE agent_defs
   SET allowed_tools = '["read_file","write_file"]',
       updated_at    = strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
 WHERE id = 'd41b7e58-2f96-4a03-8b6c-9e2d5a1f7c34'
   AND allowed_tools = '[]';

UPDATE agent_defs
   SET allowed_tools = '["read_file","list_dir"]',
       updated_at    = strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
 WHERE id = 'f0927c14-6b8d-4e71-a53f-2c9814d6b0ae'
   AND allowed_tools = '[]';
