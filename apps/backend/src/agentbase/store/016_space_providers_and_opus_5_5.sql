-- Migration 016 - a space owns its provider; untouched Opus 5 becomes Opus 5.5.
--
-- Per the 2026-09-27 decision, the app-wide provider is only where a new space
-- starts. Write the provider each inheriting space was running on into its row,
-- so no space changes provider and a later app-wide change cannot move one.
--
-- Claude Opus 5.5 replaced Opus 5 as Anthropic's recommended model, at $4/$20
-- per million tokens against $5/$25, and the maintainer chose to upgrade what
-- nobody had chosen. A space's model cannot tell a choice from the old default,
-- so every Anthropic space on Opus 5 moves. A shipped agent moves only while
-- never edited (`updated_at` still equals `created_at`); an agent someone made
-- or edited keeps the model it names. The app-wide fallback follows.

UPDATE spaces
   SET provider = COALESCE(
         (SELECT json_extract(value, '$') FROM settings WHERE key = 'provider'),
         'anthropic'),
       updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
 WHERE provider IS NULL;

UPDATE spaces
   SET model = 'claude-opus-5-5',
       updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
 WHERE provider = 'anthropic' AND model = 'claude-opus-5';

UPDATE agent_defs
   SET model = 'claude-opus-5-5',
       updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
 WHERE is_builtin = 1
   AND provider = 'anthropic'
   AND model = 'claude-opus-5'
   AND updated_at = created_at;

UPDATE settings
   SET value = '"claude-opus-5-5"',
       updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
 WHERE key = 'model' AND value = '"claude-opus-5"';
