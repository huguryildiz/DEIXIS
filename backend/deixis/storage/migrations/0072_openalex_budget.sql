-- OpenAlex's daily budget as a run met it (D248). `retry_after` is when a refused lookup may be asked again: the lookup
-- row that OpenAlex refused for lack of budget (`error_code = 'quota_exhausted'`) is not a "no copy" answer and is
-- asked again once it has passed. `openalex_budget_runs` holds one row per run that met the refusal: the reset time,
-- the cumulative counts, and the one timeline event that shows them, so a resumed or restarted run does not send what
-- the budget cannot serve and does not announce twice. Deleting a research deletes its runs and so these rows.
-- `attempt_id` identifies one OpenAlex attempt the budget refused (or kept from being sent): made when the request was
-- about to be sent, so storing the same outcome twice stores it once and two attempts are two rows.
ALTER TABLE pdf_discovery_runs ADD COLUMN retry_after TEXT;
ALTER TABLE pdf_discovery_runs ADD COLUMN attempt_id TEXT;
CREATE UNIQUE INDEX pdf_discovery_attempt ON pdf_discovery_runs(attempt_id) WHERE attempt_id IS NOT NULL;

CREATE TABLE openalex_budget_runs (
  run_id TEXT PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
  research_id TEXT NOT NULL REFERENCES researches(id) ON DELETE CASCADE,
  reset_at TEXT NOT NULL,
  refused INTEGER NOT NULL DEFAULT 0,
  skipped INTEGER NOT NULL DEFAULT 0,
  event_id INTEGER NOT NULL
);
