-- Migration 002 — spend ledger and workspace settings (BUILD_SPEC §4, §5 Phase 3).
--
-- `spend` is §4 verbatim. `settings` is an addition beyond the five tables §4
-- specifies, and the reason is the Phase 3 acceptance criterion: "switching
-- provider is a settings change with no code change" needs somewhere for that
-- choice to live. A file beside the database would split authority between
-- SQLite and the filesystem, and §2 is explicit that the database is the
-- authority. Keys are the one thing that never lands here — those stay in the
-- OS keychain (§1 constraint 4).
--
-- This is also the first migration to run against an already-populated
-- database. Everything below is additive: no existing table is altered, so a
-- v1 database with runs and events in it upgrades without touching a row.

CREATE TABLE spend (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id       TEXT REFERENCES runs(id),
  period       TEXT NOT NULL,           -- 'YYYY-MM'
  provider     TEXT NOT NULL,
  model        TEXT NOT NULL,
  input_tokens  INTEGER NOT NULL,
  output_tokens INTEGER NOT NULL,
  cost_micros  INTEGER NOT NULL,        -- integer math only, never float money
  ts           TEXT NOT NULL
);

CREATE INDEX idx_spend_period ON spend(period);

-- Key/value rather than one column per setting: Phase 7 adds a settings UI and
-- Phase 8 adds channel tokens, and each of those would otherwise be a
-- migration that rewrites a wide table. `value` is JSON so a setting can grow
-- from a string into an object without another schema change.
CREATE TABLE settings (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,             -- JSON
  updated_at TEXT NOT NULL
);
