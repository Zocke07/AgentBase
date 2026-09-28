-- Migration 012 - every space names its model; a schedule may bound its run.
--
-- Since the 2026-09-19 decision, Settings selects a provider and spaces select
-- run models; agents may still override. Upgrade inherited spaces to their
-- previous model and provider-specific spaces to that provider's default, so
-- no run changes model. Defaults match `DEFAULT_MODELS` in `store/settings.py`;
-- user-supplied Ollama models remain NULL until set.
--
-- `schedules.max_run_seconds` can extend unattended runs beyond the space
-- limit without loosening attended runs; NULL inherits.

UPDATE spaces
   SET model = COALESCE(
         (SELECT json_extract(value, '$') FROM settings WHERE key = 'model'),
         'claude-opus-5'),
       updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
 WHERE model IS NULL AND provider IS NULL;

UPDATE spaces
   SET model = CASE provider
         WHEN 'anthropic' THEN 'claude-opus-5'
         WHEN 'openai' THEN 'gpt-5.5'
       END,
       updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
 WHERE model IS NULL AND provider IN ('anthropic', 'openai');

ALTER TABLE schedules ADD COLUMN max_run_seconds INTEGER;
