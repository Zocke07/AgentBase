-- Migration 033 - the decision's date, facts and workbook (2026-10-13).
--
-- 028's Daily decision goal dropped 026's warning not to hand the decision a
-- date, and the supervisor named decisions/2026-10-13.md for the 2026-10-12
-- session. The goal mentioned annual and quarterly facts without saying
-- where they are, so the decision listed a "facts" folder that never existed.
-- A second pass the supervisor added read the binary workbook as text, about
-- 29,000 tokens of zip bytes. Only shipped text changes: the goal where it is
-- still 031's, and two passages of the decision prompt where they are still
-- as shipped.

UPDATE schedules
   SET goal = 'Ask decision to list theses/ and use the newest bull and bear file names: the date in them is the market session''s date, which in an Asian morning is the day before the local date, so do not give decision a date or a file name yourself. It reads that session''s risk checks, portfolio review, cited raw news and movers, and the annual and quarterly facts in raw/filings/, and writes decisions/{session date}.md with reasoning for every holding and considered candidate. Always call track_forecasts once with no arguments: it turns the session''s bull and bear theses into analyst forecasts, gives every other ticker a labeled random-walk baseline for 1, 2, 3, 5 and 21 trading sessions, writes predictions/{YYYY-MM}.xlsx with one sheet per session and fills due actuals in every previous month. Its result records what it wrote, so no second pass is needed to read the workbook. This is research for a person to review and executes no trades. Finish with the decision and workbook files, forecast methods and missing sources.'
 WHERE id = 'c9a4e3f2-7d5b-4e8c-9a03-2b6f4d9ebc33'
   AND goal = 'Ask decision to list theses/ and use the newest bull and bear filenames for the market session date. Read that session''s risk checks, portfolio review, cited raw news/movers and annual/quarterly facts. Write decisions/{session date}.md with reasoning for every holding and considered candidate. Always call track_forecasts once with no arguments: it turns the session''s bull and bear theses into analyst forecasts and gives every other ticker and horizon a labeled random-walk baseline. Required horizons are 1, 2, 3, 5 and 21 trading sessions. Create predictions/{YYYY-MM}.xlsx with one sheet per session and fill due actuals in every previous month. This is research for a person to review and executes no trades. Finish with the decision and workbook files, forecast methods and missing sources.';

UPDATE agent_defs
   SET system_prompt = replace(system_prompt,
'INPUT (read only): theses/bull-*.jsonl, theses/bear-*.jsonl, risk/checks-*.json,
portfolio/review-*.md, raw/calendar-*, and the raw/news-* and raw/movers-*
files whose records the theses cite.
',
'INPUT (read only): theses/bull-*.jsonl, theses/bear-*.jsonl, risk/checks-*.json,
portfolio/review-*.md, raw/calendar-*, the raw/news-* and raw/movers-* files
whose records the theses cite, and raw/filings/{TICKER}.json for a company''s
annual and quarterly facts. predictions/*.xlsx is a binary workbook that
read_file cannot show; the track_forecasts result says what it holds.
')
 WHERE id = '3ea7f62a-6177-43c2-9367-3631dea22798' AND is_builtin = 1;

UPDATE agent_defs
   SET system_prompt = replace(system_prompt,
'- Base the decision date on the newest theses filenames, not the local date.
',
'- Base the decision date and its file name on the newest theses file names,
  not the local date, even when your task names another date or file: in an
  Asian morning the local date is the day after the session''s.
')
 WHERE id = '3ea7f62a-6177-43c2-9367-3631dea22798' AND is_builtin = 1;
