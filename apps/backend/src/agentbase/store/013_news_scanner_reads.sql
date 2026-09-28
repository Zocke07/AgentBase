-- Migration 013 - the news-scanner can read its configuration.
--
-- Migration 010 gave the scanner `http_get` and `write_file`, but its prompt
-- requires local configuration. Add low-risk `read_file`, matching other
-- collectors, only when the 010 allowlist remains unchanged (in either JSON
-- spacing).

UPDATE agent_defs
   SET allowed_tools = '["http_get","read_file","write_file"]',
       updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
 WHERE id = 'c2a1ac57-ee48-4799-b94c-b01a051fdfe3'
   AND allowed_tools IN ('["http_get","write_file"]', '["http_get", "write_file"]');
