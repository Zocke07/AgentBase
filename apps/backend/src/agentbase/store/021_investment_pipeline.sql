-- Migration 021 - the shipped investment pipeline uses deterministic tools.
--
-- Roster definitions move only while never edited and while their allowlists
-- still match the shipped rows. Schedule goals move only on an exact old-text
-- match. Used installs without a saved host answer keep the previous default;
-- migration 019's five disabled schedules alone do not make an install used.

CREATE TEMP TABLE used_install AS
SELECT (
      EXISTS (SELECT 1 FROM runs)
   OR EXISTS (SELECT 1 FROM settings)
   OR EXISTS (SELECT 1 FROM spaces
               WHERE id <> '5c1e5a2e-0d4b-4c93-9a7f-3b2e8d1c6f00')
   OR EXISTS (
        SELECT 1 FROM schedules
         WHERE id NOT IN (
           'a7e2c1d0-5b3f-4c6a-9e81-0f4d2b7c9a11',
           'b8f3d2e1-6c4a-4d7b-8f92-1a5e3c8dab22',
           'c9a4e3f2-7d5b-4e8c-9a03-2b6f4d9ebc33',
           'dab5f403-8e6c-4f9d-8b14-3c7a5eafcd44',
           'ebc6a514-9f7d-4a0e-9c25-4d8b6fb0de55'
         )
      )
) AS used;

INSERT INTO settings (key, value, updated_at)
SELECT 'auto_approve_hosts', '["news.google.com","stooq.com"]',
       strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
 WHERE (SELECT used FROM used_install) = 1
   AND NOT EXISTS (SELECT 1 FROM settings WHERE key = 'auto_approve_hosts');

UPDATE agent_defs
   SET system_prompt = 'You are a market data collector. You report numbers and file paths. You
never explain a move, attribute a cause, or characterise a price.

INPUT: config/watchlist.json.

TASK
1. Read config/watchlist.json once. It must contain a non-empty watchlist array
   whose entries have ticker and sector.
2. Call read_prices first after that input read, using exactly those ticker
   symbols. The tool fetches and computes the figures, and writes
   raw/movers-{YYYY-MM-DD}.json, raw/prices/{SYMBOL}.csv and the stable
   raw/prices/summary.csv.
3. Report only the tool result: as_of, new_session, written paths, its summary
   rows, and every symbol failure.

RULES
- If the watchlist is missing or malformed, report the exact missing input and
  stop without calling read_prices.
- If read_prices reports no new session, say there is no new market session and
  stop. Do not treat a weekend or holiday as a failure.
- Do not call http_get, calculate a figure, alter a tool result, or write a
  second market file. Every number comes from read_prices verbatim.
- A failed symbol stays a failure. Never fill a gap from memory or a prior day.',
       allowed_tools = '["read_prices","read_file"]',
       updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
 WHERE id = 'c2704070-67ec-4058-ba4f-4a63f0bdf479'
   AND updated_at = created_at
   AND allowed_tools IN (
     '["http_get","read_file","write_file"]',
     '["http_get", "read_file", "write_file"]'
   );

UPDATE agent_defs
   SET system_prompt = 'You are a portfolio accountant. You describe the book as it is. You never
recommend, judge a position, or suggest an action.

TASK
1. Call compute_portfolio first. It reads portfolio/positions.csv, the stable
   price summary and config/limits.json, then writes portfolio/computed.json and
   portfolio/weights.csv.
2. If the tool succeeds, read portfolio/computed.json and write
   portfolio/review-{YYYY-MM-DD}.md.

The review states:
- total value, cash, day P&L, realised and unrealised P&L
- per position: weight, cost basis, unrealised %, days held
- concentration: largest position, top three and sector weights
- every limit crossing the tool reported

RULES
- If compute_portfolio reports a missing, stale or malformed required input,
  report that exact problem and stop without writing a review.
- Every figure is copied from compute_portfolio output or computed.json. A
  figure absent there does not appear in the review.
- State the tool''s stale flag first when it is true. Preserve null realised and
  period P&L and their reasons; never reconstruct transaction history.
- No opinions or recommendations.',
       allowed_tools = '["compute_portfolio","read_file","list_dir","write_file"]',
       updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
 WHERE id = '26846fbe-8a39-409a-9626-ccb84ab3e893'
   AND updated_at = created_at
   AND allowed_tools IN (
     '["read_file","list_dir","write_file"]',
     '["read_file", "list_dir", "write_file"]'
   );

UPDATE agent_defs
   SET system_prompt = 'You are the risk manager. You hold a veto. Your job is to find reasons not
to act. You never propose a trade.

TASK
1. Call check_limits first with the current thesis date. It reads the computed
   portfolio, limits, watchlist and both thesis files, then writes the dated
   deterministic rule-check file.
2. If the tool succeeds, read its output, the two thesis files and the saved
   calendar. Write risk/checks-{YYYY-MM-DD}.json.

For every held or thesis ticker, first restate every tool PASS or FAIL exactly.
You may not overturn, soften or reinterpret a FAIL. Then add only judgement the
rules cannot encode: correlation, event timing, liquidity, crowding and timing
risk.

Output per item:
{"ticker","verdict":"allow|reduce|block","binding_rule_or_reason",
 "max_size_pct", "notes"}

RULES
- If check_limits reports a missing or malformed input, report that exact input
  and stop without writing risk/checks.
- A hard-rule FAIL is always block. No exception is available.
- Every number is copied from check_limits or another named input. Do no
  arithmetic and invent no replacement figure.
- Under uncertainty, choose the more restrictive verdict.
- Never propose another trade, ticker or entry.',
       allowed_tools = '["check_limits","read_file","list_dir","write_file"]',
       updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
 WHERE id = '714a2fec-4ddf-4583-922e-833b6abd4fd4'
   AND updated_at = created_at
   AND allowed_tools IN (
     '["read_file","list_dir","write_file"]',
     '["read_file", "list_dir", "write_file"]'
   );

UPDATE agent_defs
   SET system_prompt = 'You are the performance reviewer. You score this system honestly, including
when the honest answer is that it does not work.

TASK
1. Call score_predictions first with the UTC month in YYYY-MM form. The tool
   appends newly resolved predictions once and writes the monthly scorecard and
   stable accuracy and calibration files.
2. If the tool succeeds, read scores/scorecard-{YYYY-MM}.json,
   scores/predictions.jsonl and the raw files as they existed at each as_of.
3. Write scores/review-{YYYY-MM}.md and propose only durable methodology
   lessons as saved context.

The review contains the tool''s tables exactly, the constant 0.5 and windows-up
baselines, calibration, the five worst misses using only information available
at prediction time, and one systematic pattern only if the sample supports it.

RULES
- If score_predictions reports a missing or corrupt input, report it and stop
  without writing a review or proposing a lesson.
- Never adjust, smooth, reweight or exclude a ledger row.
- Every score and count is copied from the tool outputs. Do no arithmetic.
- Hindsight evidence is forbidden. Say when a miss was not diagnosable from
  what was known at as_of.
- If nothing differs from noise at this sample size, say so.
- propose_memory is for standalone methodology lessons, never a market view.
  The workspace''s saved-context mode handles each proposal.',
       allowed_tools = '["score_predictions","read_file","list_dir","write_file","propose_memory"]',
       updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
 WHERE id = '8995be58-7f43-4292-a52f-3b8ee8b533a6'
   AND updated_at = created_at
   AND allowed_tools IN (
     '["read_file","list_dir","write_file","propose_memory"]',
     '["read_file", "list_dir", "write_file", "propose_memory"]'
   );

UPDATE schedules
   SET goal = 'Read the tickers in config/watchlist.json and ask market-movers first to collect their prices and the day''s movers. If it reports no new session, stop and say that the market has no new session; write and analyse nothing else. Otherwise ask news-scanner for today''s news and event-calendar for the coming 30 days, one after another. Then ask portfolio-review to compute and describe the current book. Do not analyse or recommend anything. Finish with every file written and every input that could not be collected.',
       updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
 WHERE id = 'a7e2c1d0-5b3f-4c6a-9e81-0f4d2b7c9a11'
   AND goal = 'Collect today''s inputs for the tickers in config/watchlist.json. Ask news-scanner for today''s news, market-movers for prices and the day''s movers, and event-calendar for the events of the coming 30 days, one after another; each writes its own file in raw/. Then ask portfolio-review to describe the current book from portfolio/computed.json. Do not analyse or recommend anything. Finish with the files each agent wrote and anything that could not be collected.';

UPDATE schedules
   SET goal = 'Use only the movers file from today''s new market session. If that file is missing, stop and write nothing. Otherwise ask bull-architect for the case that the watchlist tickers rise and bear-architect for the case that they fall, then ask risk-manager to check both cases against config/limits.json. Each writes its own file. Finish with the files written and any input that was missing.',
       updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
 WHERE id = 'b8f3d2e1-6c4a-4d7b-8f92-1a5e3c8dab22'
   AND goal = 'Using today''s files in raw/ and portfolio/, ask bull-architect for the case that the watchlist tickers rise and bear-architect for the case that they fall, then ask risk-manager to check both cases against config/limits.json. Each writes its own file. Finish with the files written and any input that was missing.';

UPDATE schedules
   SET goal = 'Ask research-librarian to update concept notes from the space''s own knowledge for investing concepts this week''s theses relied on. Update company notes only where raw/filings/{TICKER}/ contains filing text a person supplied; without it, skip that company rather than inventing or fetching a filing. Finish with the notes written or changed and the inputs that were absent.',
       updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
 WHERE id = 'dab5f403-8e6c-4f9d-8b14-3c7a5eafcd44'
   AND goal = 'Ask research-librarian to bring the reference notes up to date for the watchlist companies and for any investing concepts this week''s theses relied on. Finish with the notes written or changed.';

UPDATE schedules
   SET goal = 'Ask review-analyst to call score_predictions for the current UTC month first, write the scorecard review, and propose any durable methodology lessons as saved context. The workspace''s saved-context mode handles those proposals. Finish with the score and review files written, unresolved or malformed predictions reported, and any lessons proposed.',
       updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
 WHERE id = 'ebc6a514-9f7d-4a0e-9c25-4d8b6fb0de55'
   AND goal = 'Ask review-analyst to score this week''s predictions against what actually happened, write the scorecard, and propose any lessons as memories for the inbox, where a person approves them. Finish with the file written and the memories proposed.';

DROP TABLE used_install;
