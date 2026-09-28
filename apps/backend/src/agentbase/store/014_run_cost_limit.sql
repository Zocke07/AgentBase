-- Migration 014 - a space may set its own ceiling on one run's spend.
--
-- The app-wide `max_run_cost_micros` stays in key/value `settings`. Per-space
-- values sit with other limits: NULL inherits, 0 removes the ceiling, and any
-- other value caps one run in micros.

ALTER TABLE spaces ADD COLUMN max_run_cost_micros INTEGER;
