-- Migration 011 - per-tool answers, and an approval that holds for a run.
--
-- `spaces.tool_policies` maps tool names to `allow` or `deny`; NULL inherits.
-- Like `auto_approve`, it can only tighten the app-wide `settings` policy.
--
-- `approvals.scope` records one-call (`call`) or remaining-run (`run`) consent.
-- The gate reads durable state; the in-memory waiter follows it.

ALTER TABLE spaces ADD COLUMN tool_policies TEXT;

ALTER TABLE approvals ADD COLUMN scope TEXT NOT NULL DEFAULT 'call';
