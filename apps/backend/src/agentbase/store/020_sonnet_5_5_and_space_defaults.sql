-- Migration 020 - Sonnet 5.5 and efficient starting models.
--
-- Claude Sonnet 5.5 becomes Anthropic's balanced current model. Never-edited
-- shipped Sonnet agents move to it without changing updated_at, preserving the
-- guard used by later roster migrations.
--
-- A fresh Anthropic space now starts on Sonnet 5.5. A used install keeps every
-- space model and gets the old unsaved app-wide model pinned. Migration 019's
-- five disabled schedules do not by themselves make a database used.

CREATE TEMP TABLE used_install AS
SELECT (
      EXISTS (SELECT 1 FROM runs)
   OR EXISTS (SELECT 1 FROM settings)
   OR EXISTS (SELECT 1 FROM spaces
               WHERE id <> '5c1e5a2e-0d4b-4c93-9a7f-3b2e8d1c6f00')
   OR EXISTS (
        SELECT 1 FROM schedules
         WHERE id NOT IN (
           'a7e2c1d0-5b3f-4c6a-9e81-0f4d2b7c9a11',
           'b8f3d2e1-6c4a-4d7b-8f92-1a5e3c8dab22',
           'c9a4e3f2-7d5b-4e8c-9a03-2b6f4d9ebc33',
           'dab5f403-8e6c-4f9d-8b14-3c7a5eafcd44',
           'ebc6a514-9f7d-4a0e-9c25-4d8b6fb0de55'
         )
      )
) AS used;

INSERT INTO settings (key, value, updated_at)
SELECT 'model', '"claude-opus-5-5"', strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
 WHERE (SELECT used FROM used_install) = 1
   AND NOT EXISTS (SELECT 1 FROM settings WHERE key = 'model');

UPDATE spaces
   SET model = 'claude-sonnet-5-5',
       updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
 WHERE id = '5c1e5a2e-0d4b-4c93-9a7f-3b2e8d1c6f00'
   AND provider = 'anthropic'
   AND model = 'claude-opus-5-5'
   AND (SELECT used FROM used_install) = 0;

UPDATE agent_defs
   SET model = 'claude-sonnet-5-5'
 WHERE id IN (
   '0cdfe6c1-4f35-47a6-99d1-f92952984df4',
   '6dcd4865-b830-42fe-b005-cca3f9d1057a',
   'cc55c979-8117-4b68-b9ea-83d4435e1823',
   '714a2fec-4ddf-4583-922e-833b6abd4fd4',
   '8995be58-7f43-4292-a52f-3b8ee8b533a6'
 )
   AND provider = 'anthropic'
   AND model = 'claude-sonnet-5'
   AND updated_at = created_at;

DROP TABLE used_install;
