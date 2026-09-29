-- Migration 018 - autonomy is the default for new installs, not upgraded ones.
--
-- On 2026-09-29 the maintainer made autonomous runs the primary way AgentBase
-- works: low and medium risk calls are answered by policy, network calls only
-- for listed hosts, and a Discord requester may answer their own run's
-- questions. Settings keep only the keys someone saved and read the rest from
-- code, so the new defaults would silently apply to every upgraded install.
--
-- A database that has been used (it holds a run, a saved setting, a schedule
-- or a space of its own) gets the old answers written in, and keeps asking as
-- it did until someone chooses otherwise. An answer already saved is kept. A
-- fresh database holds none of these while its migrations run, so it starts
-- with the new defaults.

CREATE TEMP TABLE used_install AS
SELECT (
      EXISTS (SELECT 1 FROM runs)
   OR EXISTS (SELECT 1 FROM settings)
   OR EXISTS (SELECT 1 FROM schedules)
   OR EXISTS (SELECT 1 FROM spaces WHERE id <> '5c1e5a2e-0d4b-4c93-9a7f-3b2e8d1c6f00')
) AS used;

INSERT INTO settings (key, value, updated_at)
SELECT pinned.key, pinned.value, strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
  FROM (SELECT 'auto_approve' AS key, '[]' AS value
        UNION ALL SELECT 'auto_approve_hosts', '["*"]'
        UNION ALL SELECT 'channel_approvals', '"dashboard_only"') AS pinned
 WHERE (SELECT used FROM used_install) = 1
   AND NOT EXISTS (SELECT 1 FROM settings WHERE settings.key = pinned.key);

DROP TABLE used_install;
