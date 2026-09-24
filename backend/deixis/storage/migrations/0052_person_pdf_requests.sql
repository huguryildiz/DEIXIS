-- A person's file waiting to be read (slice 18b).
--
-- One row per file a person added to a version of a work, written in the same transaction as the attach, and only
-- when the work may be read (`waiting`). Its state moves with what caused it, in the same transaction: a reading plan
-- that takes it (`planned`, with the run and the page digest it froze), the reading decision on that file (`read`),
-- or the run that planned it ending without one (`unread`, with why). A person's retry puts an `unread` row back to
-- `waiting` and counts the attempt. A row whose question revision or criterion digest is no longer the research's is
-- stale: it is read as such and never rewritten.
CREATE TABLE person_pdf_requests (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  asset_id TEXT NOT NULL REFERENCES source_assets(id),
  scope_revision INTEGER NOT NULL,
  criterion_hash TEXT,
  status TEXT NOT NULL CHECK (status IN ('waiting', 'planned', 'read', 'unread')),
  attempt INTEGER NOT NULL DEFAULT 0,
  run_id TEXT REFERENCES runs(id),
  page_digest TEXT,
  decision_id TEXT REFERENCES stage_decisions(id),
  unread_reason TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX person_pdf_requests_file ON person_pdf_requests(research_id, asset_id);
CREATE INDEX person_pdf_requests_state ON person_pdf_requests(research_id, status);
CREATE INDEX person_pdf_requests_run ON person_pdf_requests(run_id);
