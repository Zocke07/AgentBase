-- Migration 017 - high risk is never answered by policy.
--
-- Autonomy became the default on 2026-09-29, so most calls may now run without
-- a person. run_shell, the only high-risk tool, runs commands as the user with
-- no OS isolation, and a person decides each call to it. Settings and spaces
-- now refuse to store a yes for it, and would fail to read a row that still
-- held one, so remove those answers here. Every other answer is kept exactly.
-- Agent definitions are left alone: a level they name only narrows, and the
-- app-wide list they meet no longer contains high.

UPDATE settings
   SET value = (SELECT json_group_array(level.value)
                  FROM json_each(settings.value) AS level
                 WHERE level.value <> 'high'),
       updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
 WHERE key = 'auto_approve'
   AND EXISTS (SELECT 1 FROM json_each(settings.value) WHERE value = 'high');

UPDATE settings
   SET value = json_remove(value, '$.run_shell'),
       updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
 WHERE key = 'tool_policies'
   AND json_extract(value, '$.run_shell') = 'allow';

UPDATE spaces
   SET auto_approve = (SELECT json_group_array(level.value)
                         FROM json_each(spaces.auto_approve) AS level
                        WHERE level.value <> 'high'),
       updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
 WHERE auto_approve IS NOT NULL
   AND EXISTS (SELECT 1 FROM json_each(spaces.auto_approve) WHERE value = 'high');

UPDATE spaces
   SET tool_policies = json_remove(tool_policies, '$.run_shell'),
       updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
 WHERE tool_policies IS NOT NULL
   AND json_extract(tool_policies, '$.run_shell') = 'allow';
