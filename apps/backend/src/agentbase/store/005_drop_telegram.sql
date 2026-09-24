-- Migration 005 - the Telegram channel is gone (decision of 2026-09-11, in
-- CLAUDE.md; a §6 deviation from BUILD_SPEC §5 Phase 8, which names two
-- channels).
--
-- Settings are key/value rows with a JSON value, so removing a field from
-- `WorkspaceSettings` needs no schema change - an unknown key is ignored on
-- read. Two rows are still touched here, and for a reason each.
--
-- `channel_identities` is a JSON list of `{channel, external_user_id,
-- identity}` and `channel` is validated against the channels this build
-- speaks. An entry for a channel that no longer exists would fail that
-- validation on every read, which takes `GET /settings` down with it - and
-- with it every run, since the launcher reads the settings. Filtering on read
-- would work and would log the same complaint on every request forever; a
-- migration runs exactly once, which is the property Phase 5 chose it for.
--
-- `telegram_enabled` is deleted so that the table describes the product.
-- Harmless if left, misleading to anyone who opens the file.
--
-- Nothing else refers to Telegram: no run was ever started from it (no bot
-- token ever existed), so `runs.origin` holds no such value and the events
-- table carries no `channel.inbound` for it.

UPDATE settings
SET value = (
  SELECT json_group_array(json(entry.value))
  FROM json_each(settings.value) AS entry
  WHERE json_extract(entry.value, '$.channel') != 'telegram'
)
WHERE key = 'channel_identities';

DELETE FROM settings WHERE key = 'telegram_enabled';
