-- Migration 002 - spend ledger and workspace settings (BUILD_SPEC §4, §5 Phase 3).
--
-- `spend` is §4 verbatim. `settings` makes provider changes configuration-only.
-- Store them in SQLite, the §2 authority, rather than split state with a file.
-- Keys remain in the OS keychain (§1 constraint 4).
--
-- This first migration for populated databases is additive, preserving v1
-- runs and events.

CREATE TABLE spend (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id       TEXT REFERENCES runs(id),
  period       TEXT NOT NULL,           -- 'YYYY-MM'
  provider     TEXT NOT NULL,
  model        TEXT NOT NULL,
  input_tokens  INTEGER NOT NULL,
  output_tokens INTEGER NOT NULL,
  cost_micros  INTEGER NOT NULL,        -- integer money; never float
  ts           TEXT NOT NULL
);

CREATE INDEX idx_spend_period ON spend(period);

-- Key/value JSON avoids schema changes as settings grow (for example, the
-- Phase 7 UI and Phase 8 channel tokens).
CREATE TABLE settings (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,             -- JSON
  updated_at TEXT NOT NULL
);
