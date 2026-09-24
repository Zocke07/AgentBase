-- Migration 012 - every space names its model; a schedule may bound its run.
--
-- The app-wide model is no longer chosen in Settings (the maintainer's
-- decision of 2026-09-19): Settings picks the provider, and each space
-- picks the model its runs use, with an agent still free to pick its own.
-- So a space that inherited the model gets the one it was inheriting, and a
-- space on its own provider gets that provider's default, so no run changes
-- model on the day of the upgrade. The table of defaults matches
-- `DEFAULT_MODELS` in `store/settings.py`; Ollama's model is typed by the
-- user and stays NULL until it is.
--
-- `schedules.max_run_seconds` lets an unattended run outlast the space's
-- limit (an overnight pipeline) without loosening it for attended runs;
-- NULL inherits.

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
