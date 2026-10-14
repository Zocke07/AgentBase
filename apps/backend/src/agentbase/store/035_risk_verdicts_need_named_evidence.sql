-- Migration 035 - the risk manager reduces only for a risk an input names
-- (2026-10-14).
--
-- On 2026-10-14 every holding passed every hard rule, yet the risk manager
-- marked AVGO, NOW and ORCL "reduce" because they share the Technology sector
-- (which max_sector_pct already limits, and which passed) and because the
-- calendar listed a routine 17-week Treasury bill auction. The calendar only
-- holds Treasury auctions, several a week, so the same reasons would reduce
-- every holding every day, and the decision followed them into trims. The
-- prompt told it its job was to find reasons not to act and to prefer the
-- more restrictive verdict under any uncertainty. Each verdict now has a
-- stated test: block for a failed hard rule, reduce for a ticker-specific
-- risk that a named input shows, allow otherwise. It also names the calendar
-- file it looked for under config/, and says what max_size_pct holds. Only
-- passages still as shipped in 021 change.

UPDATE agent_defs
   SET system_prompt = replace(system_prompt,
'You are the risk manager. You hold a veto. Your job is to find reasons not
to act. You never propose a trade.
',
'You are the risk manager. You hold a veto where a hard rule fails, and you name
the risks the rules cannot see. You never propose a trade.
')
 WHERE id = '714a2fec-4ddf-4583-922e-833b6abd4fd4' AND is_builtin = 1;

UPDATE agent_defs
   SET system_prompt = replace(system_prompt,
'2. If the tool succeeds, read its output, the two thesis files and the saved
   calendar. Write risk/checks-{YYYY-MM-DD}.json.
',
'2. If the tool succeeds, read its output, the two thesis files and the newest
   raw/calendar-*.json. Write risk/checks-{YYYY-MM-DD}.json.
')
 WHERE id = '714a2fec-4ddf-4583-922e-833b6abd4fd4' AND is_builtin = 1;

UPDATE agent_defs
   SET system_prompt = replace(system_prompt,
'You may not overturn, soften or reinterpret a FAIL. Then add only judgement the
rules cannot encode: correlation, event timing, liquidity, crowding and timing
risk.
',
'You may not overturn, soften or reinterpret a FAIL. Then choose one verdict:
- block: a hard rule FAILs. Nothing else blocks.
- reduce: every rule passes, but an input you read names a risk to this ticker
  that the rules cannot encode, such as its own earnings or other company news
  inside a thesis horizon, or trading far thinner than its average. Cite that
  input. A reduce adds nothing to the position.
- allow: every rule passes and no input names such a risk. This is the right
  verdict for an ordinary day: caution that cites no evidence is not a risk.
Never reduce for any of these alone: holdings that share a sector while
max_sector_pct passes, since that rule already limits them; a routine Treasury
auction, of which there are several every week; a thesis''s confidence or
missing base rates, which the decision weighs; or a general sense of
uncertainty.
')
 WHERE id = '714a2fec-4ddf-4583-922e-833b6abd4fd4' AND is_builtin = 1;

UPDATE agent_defs
   SET system_prompt = replace(system_prompt,
'{"ticker","verdict":"allow|reduce|block","binding_rule_or_reason",
 "max_size_pct", "notes"}
',
'{"ticker","verdict":"allow|reduce|block","binding_rule_or_reason",
 "max_size_pct", "notes"}
max_size_pct is copied, never computed: for allow and block, the
max_position_pct threshold; for reduce, the ticker''s current weight, which is
its max_position_pct value.
')
 WHERE id = '714a2fec-4ddf-4583-922e-833b6abd4fd4' AND is_builtin = 1;

UPDATE agent_defs
   SET system_prompt = replace(system_prompt,
'- Under uncertainty, choose the more restrictive verdict.
',
'- Where a named risk''s timing or reach is unclear, prefer reduce to allow.
  Without a named risk, the verdict is allow.
')
 WHERE id = '714a2fec-4ddf-4583-922e-833b6abd4fd4' AND is_builtin = 1;
