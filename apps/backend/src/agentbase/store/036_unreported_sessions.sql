-- Migration 036 - a dated holdings file is noted, not a stop, and sessions
-- with no report are named (2026-10-20).
--
-- The holdings file had not been saved for a week, so compute_portfolio's
-- stale flag was true, and the portfolio review stopped without writing: its
-- prompt both said to stop on a stale input and to state the stale flag
-- first. An unchanged holdings file is not an error, so the review now says
-- when the holdings were last saved and carries on. AgentBase was also closed
-- for three mornings, and nothing said the 14 to 16 October sessions had no
-- report; compute_portfolio now records them, with what changed since the
-- report before, under since_previous. The review states it, and the decision
-- reads computed.json and names the unreported sessions under its table.
-- Only passages still as shipped change.

UPDATE agent_defs
   SET system_prompt = replace(system_prompt,
'- If compute_portfolio reports a missing, stale or malformed required input,
  report that exact problem and stop without writing a review.
',
'- If compute_portfolio reports a missing or malformed required input, report
  that exact problem and stop without writing a review.
')
 WHERE id = '26846fbe-8a39-409a-9626-ccb84ab3e893' AND is_builtin = 1;

UPDATE agent_defs
   SET system_prompt = replace(system_prompt,
'- State the tool''s stale flag first when it is true. Preserve null realised and
  period P&L and their reasons; never reconstruct transaction history.
',
'- When the tool''s stale flag is true, say first that the holdings were last
  saved on its positions_date, then write the review as usual: an unchanged
  holdings file is not an error. Preserve null realised and period P&L and
  their reasons; never reconstruct transaction history.
')
 WHERE id = '26846fbe-8a39-409a-9626-ccb84ab3e893' AND is_builtin = 1;

UPDATE agent_defs
   SET system_prompt = replace(system_prompt,
'- every limit crossing the tool reported
',
'- every limit crossing the tool reported
- since the previous report, from since_previous: the session it compares
  with, every session in skipped_sessions as having no report, the change in
  total value and each holding''s price change; when since_previous is null,
  that there is no earlier report to compare with
')
 WHERE id = '26846fbe-8a39-409a-9626-ccb84ab3e893' AND is_builtin = 1;

UPDATE agent_defs
   SET system_prompt = replace(system_prompt,
'portfolio/review-*.md, raw/calendar-*, the raw/news-* and raw/movers-* files
',
'portfolio/review-*.md, portfolio/computed.json, raw/calendar-*, the raw/news-*
and raw/movers-* files
')
 WHERE id = '3ea7f62a-6177-43c2-9367-3631dea22798' AND is_builtin = 1;

UPDATE agent_defs
   SET system_prompt = replace(system_prompt,
'   write one row with ticker none and action pass.
',
'   write one row with ticker none and action pass.
   When portfolio/computed.json''s since_previous lists skipped_sessions, say
   under the table that those sessions have no research or forecasts.
')
 WHERE id = '3ea7f62a-6177-43c2-9367-3631dea22798' AND is_builtin = 1;
