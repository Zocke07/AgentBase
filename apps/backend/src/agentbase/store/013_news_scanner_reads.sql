-- Migration 013 - the news-scanner can read its configuration.
--
-- Its prompt begins "INPUT: config/watchlist.json for tickers,
-- config/sources.json for feed URLs", and 010 shipped it with `http_get`
-- and `write_file` only, so the first real run tried to fetch its own
-- configuration over HTTP and stopped. `read_file` is low risk and the
-- other collectors already have it. Guarded on the allowlist still being
-- what 010 wrote, in either JSON spacing, so an edited row is left alone.

UPDATE agent_defs
   SET allowed_tools = '["http_get","read_file","write_file"]',
       updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
 WHERE id = 'c2a1ac57-ee48-4799-b94c-b01a051fdfe3'
   AND allowed_tools IN ('["http_get","write_file"]', '["http_get", "write_file"]');
