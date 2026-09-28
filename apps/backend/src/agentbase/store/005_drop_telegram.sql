-- Migration 005 removes Telegram (2026-09-11 decision in CLAUDE.md), a §6
-- deviation from BUILD_SPEC §5 Phase 8.
--
-- JSON key/value settings need no schema change for a removed
-- `WorkspaceSettings` field; unknown keys are ignored on read.
--
-- Remove Telegram entries from `channel_identities`: validation would otherwise
-- make every `GET /settings` fail, preventing launcher reads. A one-time
-- migration avoids repeated read-time errors.
--
-- Delete `telegram_enabled` so settings describe the product.
--
-- No run or event can reference Telegram: no bot token ever existed.

UPDATE settings
SET value = (
  SELECT json_group_array(json(entry.value))
  FROM json_each(settings.value) AS entry
  WHERE json_extract(entry.value, '$.channel') != 'telegram'
)
WHERE key = 'channel_identities';

DELETE FROM settings WHERE key = 'telegram_enabled';
