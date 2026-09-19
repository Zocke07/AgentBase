-- Migration 014 - a space may set its own ceiling on one run's spend.
--
-- The app-wide `max_run_cost_micros` lives in `settings` as a key/value row
-- and needs no column. A space's copy sits beside its other limits: NULL
-- inherits, 0 lifts the ceiling for that space, anything else is the most
-- one run there may spend, in micros.

ALTER TABLE spaces ADD COLUMN max_run_cost_micros INTEGER;
