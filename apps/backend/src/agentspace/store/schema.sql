-- Migration 001 — the event spine (BUILD_SPEC §4, §5 Phase 2).
--
-- Only the two tables Phase 2 actually uses. §4 also specifies `spend`,
-- `agent_defs` and `approvals`; those arrive as migrations 002+ in Phases 3, 5
-- and 6, because §5 says do not build ahead — and because a migration runner
-- whose second step never executes before release is untested machinery.
--
-- Later migrations live beside this file as `002_<name>.sql` and are listed in
-- `db.py`'s MIGRATIONS tuple.

CREATE TABLE runs (
  id           TEXT PRIMARY KEY,        -- uuid4
  goal         TEXT NOT NULL,
  status       TEXT NOT NULL,           -- pending|running|paused|completed|failed|cancelled
  origin       TEXT NOT NULL,           -- ui|discord|telegram
  origin_ref   TEXT,                    -- channel/thread id for replies
  created_at   TEXT NOT NULL,
  finished_at  TEXT
);

CREATE TABLE events (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id    TEXT NOT NULL REFERENCES runs(id),
  seq       INTEGER NOT NULL,
  agent_id  TEXT,
  type      TEXT NOT NULL,
  payload   TEXT NOT NULL,              -- JSON
  ts        TEXT NOT NULL,
  UNIQUE(run_id, seq)
);

CREATE INDEX idx_events_run_seq ON events(run_id, seq);
