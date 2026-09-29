-- Migration 019 - the shipped investment roster runs as a pipeline of its own.
--
-- On 2026-09-29 the maintainer made autonomous workflows the primary way
-- AgentBase works and asked that the shipped examples show it. Three changes:
--
-- 1. Five agents asked the app to pre-approve only low risk, so under the new
--    autonomous default each stage's one write (and the reviewer's memory
--    proposal) became a question nobody is there to answer in a scheduled run.
--    They now name low and medium, which only narrows the app-wide policy as
--    before. A row whose levels or tools someone changed is left exactly as it
--    is. `updated_at` is not touched, so "never edited by a person" still reads
--    true for a later migration.
--
-- 2. The news scanner reads RSS and Atom feeds since 015, so its role no longer
--    mentions social discussion, while the role is still the shipped one.
--
-- 3. The default space gets the pipeline as five schedules, all switched off,
--    so nothing spends money until someone turns them on from Home. The morning
--    collection runs on weekdays; the theses, then the decision, follow it as
--    chained stages; knowledge and review run weekly. A schedule is added only
--    while every agent its goal names is still in the roster, and a stage only
--    when the schedule it follows was added.

UPDATE agent_defs SET auto_approve = '["low","medium"]'
 WHERE id IN ('6dcd4865-b830-42fe-b005-cca3f9d1057a', 'cc55c979-8117-4b68-b9ea-83d4435e1823')
   AND space_id = '5c1e5a2e-0d4b-4c93-9a7f-3b2e8d1c6f00'
   AND auto_approve = '["low"]'
   AND allowed_tools IN (
     '["read_file","list_dir","search_knowledge","write_file"]',
     '["read_file", "list_dir", "search_knowledge", "write_file"]'
   );

UPDATE agent_defs SET auto_approve = '["low","medium"]'
 WHERE id IN ('714a2fec-4ddf-4583-922e-833b6abd4fd4', '3ea7f62a-6177-43c2-9367-3631dea22798')
   AND space_id = '5c1e5a2e-0d4b-4c93-9a7f-3b2e8d1c6f00'
   AND auto_approve = '["low"]'
   AND allowed_tools IN (
     '["read_file","list_dir","write_file"]',
     '["read_file", "list_dir", "write_file"]'
   );

UPDATE agent_defs SET auto_approve = '["low","medium"]'
 WHERE id = '8995be58-7f43-4292-a52f-3b8ee8b533a6'
   AND space_id = '5c1e5a2e-0d4b-4c93-9a7f-3b2e8d1c6f00'
   AND auto_approve = '["low"]'
   AND allowed_tools IN (
     '["read_file","list_dir","write_file","propose_memory"]',
     '["read_file", "list_dir", "write_file", "propose_memory"]'
   );

UPDATE agent_defs
   SET role = 'Collects public news about watchlist tickers into a fixed schema. Performs no analysis.'
 WHERE id = 'c2a1ac57-ee48-4799-b94c-b01a051fdfe3'
   AND role = 'Collects public news and social discussion about watchlist tickers into a fixed schema. Performs no analysis.';

-- A roster agent counts only while it is still in the default space under its
-- shipped id; its name alone could belong to something a person made.
CREATE TEMP TABLE roster AS
SELECT id FROM agent_defs WHERE space_id = '5c1e5a2e-0d4b-4c93-9a7f-3b2e8d1c6f00';

INSERT INTO schedules
  (id, space_id, name, goal, cadence, missed, enabled, next_run_at, max_run_seconds,
   created_at, updated_at)
SELECT
  'a7e2c1d0-5b3f-4c6a-9e81-0f4d2b7c9a11',
  '5c1e5a2e-0d4b-4c93-9a7f-3b2e8d1c6f00',
  'Morning collection',
  'Collect today''s inputs for the tickers in config/watchlist.json. Ask news-scanner for today''s news, market-movers for prices and the day''s movers, and event-calendar for the events of the coming 30 days, one after another; each writes its own file in raw/. Then ask portfolio-review to describe the current book from portfolio/computed.json. Do not analyse or recommend anything. Finish with the files each agent wrote and anything that could not be collected.',
  '{"at": "07:00", "kind": "weekly", "weekdays": [0, 1, 2, 3, 4]}',
  'run_on_launch', 0, NULL, 1800,
  strftime('%Y-%m-%dT%H:%M:%S+00:00','now'), strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
WHERE NOT EXISTS (SELECT 1 FROM schedules WHERE id = 'a7e2c1d0-5b3f-4c6a-9e81-0f4d2b7c9a11')
  AND (SELECT COUNT(*) FROM roster WHERE id IN (
        'c2a1ac57-ee48-4799-b94c-b01a051fdfe3', 'c2704070-67ec-4058-ba4f-4a63f0bdf479',
        '1ab3b5f3-6c98-4297-b7ff-35971356dd27', '26846fbe-8a39-409a-9626-ccb84ab3e893')) = 4;

INSERT INTO schedules
  (id, space_id, name, goal, cadence, missed, enabled, next_run_at, max_run_seconds,
   created_at, updated_at)
SELECT
  'b8f3d2e1-6c4a-4d7b-8f92-1a5e3c8dab22',
  '5c1e5a2e-0d4b-4c93-9a7f-3b2e8d1c6f00',
  'Theses and risk',
  'Using today''s files in raw/ and portfolio/, ask bull-architect for the case that the watchlist tickers rise and bear-architect for the case that they fall, then ask risk-manager to check both cases against config/limits.json. Each writes its own file. Finish with the files written and any input that was missing.',
  '{"kind": "after", "schedule_id": "a7e2c1d0-5b3f-4c6a-9e81-0f4d2b7c9a11"}',
  'run_on_launch', 0, NULL, 1800,
  strftime('%Y-%m-%dT%H:%M:%S+00:00','now'), strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
WHERE NOT EXISTS (SELECT 1 FROM schedules WHERE id = 'b8f3d2e1-6c4a-4d7b-8f92-1a5e3c8dab22')
  AND EXISTS (SELECT 1 FROM schedules WHERE id = 'a7e2c1d0-5b3f-4c6a-9e81-0f4d2b7c9a11')
  AND (SELECT COUNT(*) FROM roster WHERE id IN (
        '6dcd4865-b830-42fe-b005-cca3f9d1057a', 'cc55c979-8117-4b68-b9ea-83d4435e1823',
        '714a2fec-4ddf-4583-922e-833b6abd4fd4')) = 3;

INSERT INTO schedules
  (id, space_id, name, goal, cadence, missed, enabled, next_run_at, max_run_seconds,
   created_at, updated_at)
SELECT
  'c9a4e3f2-7d5b-4e8c-9a03-2b6f4d9ebc33',
  '5c1e5a2e-0d4b-4c93-9a7f-3b2e8d1c6f00',
  'Daily decision',
  'Ask decision to write today''s decisions file from the bull and bear theses, the risk checks and the portfolio review. It is a recommendation for a person to review: nothing is bought or sold, and nothing is executed. Finish with the file written.',
  '{"kind": "after", "schedule_id": "b8f3d2e1-6c4a-4d7b-8f92-1a5e3c8dab22"}',
  'run_on_launch', 0, NULL, 1800,
  strftime('%Y-%m-%dT%H:%M:%S+00:00','now'), strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
WHERE NOT EXISTS (SELECT 1 FROM schedules WHERE id = 'c9a4e3f2-7d5b-4e8c-9a03-2b6f4d9ebc33')
  AND EXISTS (SELECT 1 FROM schedules WHERE id = 'b8f3d2e1-6c4a-4d7b-8f92-1a5e3c8dab22')
  AND EXISTS (SELECT 1 FROM roster WHERE id = '3ea7f62a-6177-43c2-9367-3631dea22798');

INSERT INTO schedules
  (id, space_id, name, goal, cadence, missed, enabled, next_run_at, max_run_seconds,
   created_at, updated_at)
SELECT
  'dab5f403-8e6c-4f9d-8b14-3c7a5eafcd44',
  '5c1e5a2e-0d4b-4c93-9a7f-3b2e8d1c6f00',
  'Weekly knowledge',
  'Ask research-librarian to bring the reference notes up to date for the watchlist companies and for any investing concepts this week''s theses relied on. Finish with the notes written or changed.',
  '{"at": "09:00", "kind": "weekly", "weekdays": [5]}',
  'run_on_launch', 0, NULL, 1800,
  strftime('%Y-%m-%dT%H:%M:%S+00:00','now'), strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
WHERE NOT EXISTS (SELECT 1 FROM schedules WHERE id = 'dab5f403-8e6c-4f9d-8b14-3c7a5eafcd44')
  AND EXISTS (SELECT 1 FROM roster WHERE id = '0cdfe6c1-4f35-47a6-99d1-f92952984df4');

INSERT INTO schedules
  (id, space_id, name, goal, cadence, missed, enabled, next_run_at, max_run_seconds,
   created_at, updated_at)
SELECT
  'ebc6a514-9f7d-4a0e-9c25-4d8b6fb0de55',
  '5c1e5a2e-0d4b-4c93-9a7f-3b2e8d1c6f00',
  'Weekly review',
  'Ask review-analyst to score this week''s predictions against what actually happened, write the scorecard, and propose any lessons as memories for the inbox, where a person approves them. Finish with the file written and the memories proposed.',
  '{"at": "18:00", "kind": "weekly", "weekdays": [6]}',
  'run_on_launch', 0, NULL, 1800,
  strftime('%Y-%m-%dT%H:%M:%S+00:00','now'), strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
WHERE NOT EXISTS (SELECT 1 FROM schedules WHERE id = 'ebc6a514-9f7d-4a0e-9c25-4d8b6fb0de55')
  AND EXISTS (SELECT 1 FROM roster WHERE id = '8995be58-7f43-4292-a52f-3b8ee8b533a6');

DROP TABLE roster;
