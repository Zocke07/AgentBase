-- Migration 007 - local Markdown retrieval and durable agent memory.
--
-- The knowledge itself remains in each space folder, not in SQLite. This
-- migration only makes the new read-only search tool available to seeded
-- roles that still carry an exact shipped allowlist. A user-edited allowlist
-- is preserved.

UPDATE agent_defs
   SET allowed_tools = '["read_file","list_dir","search_knowledge"]',
       updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
 WHERE is_builtin = 1
   AND name IN ('researcher', 'reviewer')
   AND allowed_tools IN ('["read_file","list_dir"]', '["read_file", "list_dir"]');

UPDATE agent_defs
   SET allowed_tools = '["read_file","write_file","search_knowledge"]',
       updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
 WHERE is_builtin = 1
   AND name = 'writer'
   AND allowed_tools IN ('["read_file","write_file"]', '["read_file", "write_file"]');

