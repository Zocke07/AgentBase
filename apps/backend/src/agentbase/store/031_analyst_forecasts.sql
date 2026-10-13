-- Migration 031 - the session's theses become forecasts (2026-10-13).
--
-- The decision was told to copy each thesis's expected_return_pct into a
-- scenario, a field no thesis wrote, so every forecast in the workbook was
-- the unchanged close; it also narrowed track_forecasts to the stocks it
-- discussed. track_forecasts now reads the session's bull and bear theses
-- itself, and the decision calls it once with no arguments. Only these
-- passages change, and only where they are still the shipped text: a
-- prompt or goal edited there keeps its edit, and everything else stays.

UPDATE agent_defs
   SET system_prompt = replace(system_prompt,
'4. FORECAST TRACKING: call track_forecasts for the newest complete market
   session, using no as_of argument. It creates predictions/{YYYY-MM}.xlsx
   with one daily sheet and predictions/forecasts.json, updating actuals in
   prior months. Include its file paths, methods, counts and limitations.
',
'4. FORECAST TRACKING: call track_forecasts once, with no arguments, for the
   newest complete market session. It turns that session''s theses into
   analyst forecasts and creates predictions/{YYYY-MM}.xlsx with one daily
   sheet and predictions/forecasts.json, updating actuals in prior months.
   Include its file paths, methods, counts and limitations.
')
 WHERE id = '3ea7f62a-6177-43c2-9367-3631dea22798' AND is_builtin = 1;

UPDATE agent_defs
   SET system_prompt = replace(system_prompt,
'FORECAST TASK
- Always call track_forecasts, including when every action is pass or the
  evidence supports no trade. Price research remains useful when risk blocks
  adding a position; a forecast is not permission to trade.
- For supported, distinct bull or bear scenarios copy expected_return_pct to
  scenario_return_pct for that ticker and horizon, together with confidence,
  rationale (the assumption and invalidation), and saved evidence_ids.
  Arbitrate conflicting cases explicitly. Never average or calculate targets.
- Call track_forecasts once with the selected scenarios. It fills every other
  ticker/horizon with an explicitly labeled unchanged-price random-walk
  baseline and historical-volatility uncertainty interval. With no supported
  scenarios call it without forecasts. That is an honest benchmark, not a
  news-based claim or calibrated probability of a future price.
- Required horizons are 1, 2, 3, 5 and 21 trading sessions. Copy the tool''s
  computed targets exactly; explain methods, assumptions and source gaps.
',
'FORECAST TASK
- Always call track_forecasts once, with no arguments, including when every
  action is pass or the evidence supports no trade. Price research remains
  useful when risk blocks adding a position; a forecast is not permission to
  trade.
- Do not pass symbols, as_of or forecasts. The tool reads this session''s
  theses itself and covers every stock in the price summary; narrowing the
  call leaves stocks without forecasts.
- A bull or bear thesis becomes an analyst forecast from its direction and
  magnitude band, or from its expected_return_pct when that lies inside the
  band. Where bull and bear disagree at a horizon, where a thesis''s evidence
  is missing, and wherever no thesis exists, the tool records an explicitly
  labeled unchanged-price random-walk baseline with a historical-volatility
  interval. That is an honest benchmark, not a news-based claim or a
  calibrated probability of a future price.
- Report analyst_forecasts, thesis_conflicts, thesis_problems and skipped
  reasons as the tool states them. When not_issued says the market is
  trading, say that no forecasts were recorded and that the next run after
  the close records them.
- Required horizons are 1, 2, 3, 5 and 21 trading sessions. Copy the tool''s
  computed targets exactly; explain methods, assumptions and source gaps.
')
 WHERE id = '3ea7f62a-6177-43c2-9367-3631dea22798' AND is_builtin = 1;

UPDATE schedules
   SET goal = replace(goal,
'Always call track_forecasts once, with supported conditional scenario assumptions when available and labeled random-walk baselines for the remaining ticker/horizon pairs.',
'Always call track_forecasts once with no arguments: it turns the session''s bull and bear theses into analyst forecasts and gives every other ticker and horizon a labeled random-walk baseline.')
 WHERE id = 'c9a4e3f2-7d5b-4e8c-9a03-2b6f4d9ebc33';

UPDATE schedules
   SET goal = replace(goal,
'Report baseline versus agent scenario forecast coverage,',
'Report random-walk baseline, analyst thesis and agent scenario forecast coverage,')
 WHERE id = 'ebc6a514-9f7d-4a0e-9c25-4d8b6fb0de55';
