-- deixis:foreign-keys-off
-- Open-access PDFs are collected in a run of their own before an answer (D49). SQLite cannot widen a CHECK in place, and
-- six tables reference runs, so the table is rebuilt as in 0019 and 0022; migrate() checks foreign keys.
CREATE TABLE runs_new (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  scope_revision INTEGER NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('discovery', 'answer', 'table_columns', 'table_fill', 'cell_recheck', 'research_title', 'pdf_collection')),
  status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'pause_requested', 'paused', 'completed', 'failed', 'cancelled')),
  stage TEXT NOT NULL CHECK (stage IN ('intake', 'discovery', 'screening', 'inspection', 'answer', 'extraction', 'synthesis', 'candidate', 'claim_check', 'export')),
  pause_reason TEXT,
  error_json TEXT,
  budget_json TEXT NOT NULL,
  usage_json TEXT NOT NULL DEFAULT '{}',
  idempotency_key TEXT UNIQUE,
  -- Table runs: {"table_id", "column_ids", "cell_id", "include_stale"}. NULL for other runs.
  target_json TEXT,
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
INSERT INTO runs_new (id, research_id, scope_revision, kind, status, stage, pause_reason, error_json, budget_json,
                      usage_json, idempotency_key, target_json, version, created_at, updated_at)
  SELECT id, research_id, scope_revision, kind, status, stage, pause_reason, error_json, budget_json,
         usage_json, idempotency_key, target_json, version, created_at, updated_at FROM runs;
DROP TABLE runs;
ALTER TABLE runs_new RENAME TO runs;
CREATE INDEX runs_status ON runs(status, created_at);
