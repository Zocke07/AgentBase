-- Migration 009 - scheduled runs (BUILD_SPEC §5 Phase 13).
--
-- A schedule belongs to one space and starts runs in it while the app is
-- open. `next_run_at` is the one moving part: the scheduler reads the rows
-- that are due, launches each once, and moves it to the following occurrence.
-- Times are stored in UTC. The cadence is in the machine's local time, so
-- the next occurrence is always recomputed from the cadence and the clock
-- rather than added to the previous time, and a clock change or a DST switch
-- cannot accumulate drift.

CREATE TABLE schedules (
  id            TEXT PRIMARY KEY,
  space_id      TEXT NOT NULL REFERENCES spaces(id),
  name          TEXT NOT NULL,
  goal          TEXT NOT NULL,
  cadence       TEXT NOT NULL,                        -- JSON, see store/schedules.py
  missed        TEXT NOT NULL DEFAULT 'run_on_launch', -- run_on_launch|skip
  enabled       INTEGER NOT NULL DEFAULT 1,
  next_run_at   TEXT,                                 -- UTC; NULL while disabled
  last_run_at   TEXT,
  last_run_id   TEXT REFERENCES runs(id) ON DELETE SET NULL,
  last_outcome  TEXT,                                 -- what the scheduler last did, in words
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);

CREATE INDEX idx_schedules_space ON schedules(space_id);
CREATE INDEX idx_schedules_due ON schedules(enabled, next_run_at);
