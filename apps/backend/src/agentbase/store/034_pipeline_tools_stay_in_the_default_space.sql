-- Migration 034 - the investment pipeline's tools stay in the default space
-- (2026-10-13).
--
-- At the maintainer's request, what was built for the default space's
-- investment pipeline stays there, and agents in every other space use the
-- general tools. Agents there can no longer be given the seven pipeline tools,
-- and a run there offers and permits none of them, so take them off any such
-- agent and out of its space's per-tool answers. The rest of each list keeps
-- its order. The default space's rows are not touched.

UPDATE agent_defs
   SET allowed_tools = (SELECT json_group_array(tool.value)
                          FROM json_each(agent_defs.allowed_tools) AS tool
                         WHERE tool.value NOT IN ('read_market', 'read_company_reports',
                                                  'read_prices', 'compute_portfolio',
                                                  'check_limits', 'score_predictions',
                                                  'track_forecasts')),
       updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
 WHERE space_id <> '5c1e5a2e-0d4b-4c93-9a7f-3b2e8d1c6f00'
   AND EXISTS (SELECT 1 FROM json_each(agent_defs.allowed_tools)
                WHERE value IN ('read_market', 'read_company_reports', 'read_prices',
                                'compute_portfolio', 'check_limits', 'score_predictions',
                                'track_forecasts'));

UPDATE spaces
   SET tool_policies = json_remove(tool_policies, '$.read_market', '$.read_company_reports',
                                   '$.read_prices', '$.compute_portfolio', '$.check_limits',
                                   '$.score_predictions', '$.track_forecasts'),
       updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
 WHERE id <> '5c1e5a2e-0d4b-4c93-9a7f-3b2e8d1c6f00'
   AND tool_policies IS NOT NULL
   AND EXISTS (SELECT 1 FROM json_each(spaces.tool_policies)
                WHERE key IN ('read_market', 'read_company_reports', 'read_prices',
                              'compute_portfolio', 'check_limits', 'score_predictions',
                              'track_forecasts'));
