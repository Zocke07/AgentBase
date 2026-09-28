-- Migration 009 - scheduled runs (BUILD_SPEC §5 Phase 13).
--
-- Each schedule launches runs in its space while the app is open. The scheduler
-- launches due rows once, then advances `next_run_at`. Store times in UTC, but
-- recompute local-time cadence from the clock to prevent DST or clock-change
-- drift.

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
  last_outcome  TEXT,                                 -- scheduler's last action
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);

CREATE INDEX idx_schedules_space ON schedules(space_id);
CREATE INDEX idx_schedules_due ON schedules(enabled, next_run_at);
