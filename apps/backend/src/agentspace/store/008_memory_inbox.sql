-- Migration 008 - agent-proposed memories enter a user-curated inbox.
--
-- Only exact v0.2 defaults are widened. A user-edited allowlist remains
-- untouched, including one that deliberately removed knowledge access.

UPDATE agent_defs
   SET allowed_tools = '["read_file","list_dir","search_knowledge","propose_memory"]',
       updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
 WHERE is_builtin = 1
   AND name IN ('researcher', 'reviewer')
   AND allowed_tools IN (
       '["read_file","list_dir","search_knowledge"]',
       '["read_file", "list_dir", "search_knowledge"]'
   );

UPDATE agent_defs
   SET allowed_tools = '["read_file","write_file","search_knowledge","propose_memory"]',
       updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
 WHERE is_builtin = 1
   AND name = 'writer'
   AND allowed_tools IN (
       '["read_file","write_file","search_knowledge"]',
       '["read_file", "write_file", "search_knowledge"]'
   );
