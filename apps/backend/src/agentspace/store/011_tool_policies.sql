-- Migration 011 - per-tool answers, and an approval that holds for a run.
--
-- `spaces.tool_policies` is a JSON object of tool name to `allow` or `deny`,
-- NULL meaning inherit, beside `auto_approve` and with the same rule: a
-- space can only make the app-wide answer stricter. The app-wide map lives
-- in `settings` as a key/value row and needs no column.
--
-- `approvals.scope` records whether a person's yes was for the one call
-- (`call`, every row so far) or for every call to that tool in the rest of
-- the run (`run`). The gate reads it the way it reads a denial: from the
-- table, so the durable state decides and the in-memory waiter follows.

ALTER TABLE spaces ADD COLUMN tool_policies TEXT;

ALTER TABLE approvals ADD COLUMN scope TEXT NOT NULL DEFAULT 'call';
