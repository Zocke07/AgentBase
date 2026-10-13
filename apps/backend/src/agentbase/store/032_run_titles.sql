-- Migration 032 - an automation's run carries its name (2026-10-13).
--
-- The Runs view named every run by its goal. An automation's goal is a
-- paragraph of instructions, so one morning's runs looked alike. A run now
-- keeps the title it started with: its schedule's name, or the stocks a
-- market alert explains. Earlier runs take the same from their schedule or
-- alert batch where that still exists. A person's own run has no title; its
-- goal is what they wrote.

ALTER TABLE runs ADD COLUMN title TEXT;

UPDATE runs
   SET title = (SELECT name FROM schedules WHERE schedules.id = runs.origin_ref)
 WHERE origin IN ('schedule', 'automation');

UPDATE runs
   SET title = 'Market alert: ' || (
         SELECT group_concat(symbol, ', ')
           FROM (SELECT symbol
                   FROM market_alerts
                  WHERE market_alerts.batch_id = runs.origin_ref
                  GROUP BY symbol
                  ORDER BY min(rowid)))
 WHERE origin = 'monitor'
   AND EXISTS (SELECT 1 FROM market_alerts WHERE market_alerts.batch_id = runs.origin_ref);
