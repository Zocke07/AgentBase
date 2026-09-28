-- Migration 004 - the approval gate's durable half (BUILD_SPEC §4, §5 Phase 6).
--
-- `approvals` is §4 verbatim and arrives with its Phase 6 use, avoiding
-- unexercised pre-release schema.
--
-- The gate waits on an in-memory `asyncio.Future`; events remain the §2 source
-- of decision history. This table indexes current outstanding approvals for the
-- Phase 7 dialog and `POST /approvals/{id}` without scanning the event log.
--
-- `expired` is required: restart destroys a pending row's in-process waiter.
-- `ApprovalStore.expire_orphaned_pending` closes such rows at startup, so an
-- HTTP resolution cannot succeed without waking anyone.

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

-- Supports outstanding-by-run queries; the primary key resolves an ID.
CREATE INDEX idx_approvals_run_status ON approvals(run_id, status);

-- Grant seeded built-ins the tools now implemented.
--
-- Migration 003 used empty allowlists until tools existed; fresh installs now
-- receive the Phase 5 defaults.
--
-- Restrict changes to the seeded `[]` allowlist to preserve edits. An intentional
-- empty list receives the default once, then may be emptied again.
--
-- Grant no `auto_approve`: §5 Phase 6 requires manual approval and prevents
-- built-ins from escalating their own privileges.
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
