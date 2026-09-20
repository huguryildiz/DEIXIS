-- One frozen protocol record per research revision (SW14.1): what was searched for and under which rules, hashed over
-- the canonical form and never edited in place. A change opens a new protocol revision with its reason.
CREATE TABLE protocol_records (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  scope_revision INTEGER NOT NULL,
  protocol_revision INTEGER NOT NULL,
  reason TEXT,
  body_json TEXT NOT NULL,
  body_sha256 TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (research_id, protocol_revision)
);
CREATE INDEX protocol_records_scope ON protocol_records(research_id, scope_revision, protocol_revision);
CREATE TRIGGER protocol_records_no_update BEFORE UPDATE ON protocol_records
BEGIN SELECT RAISE(ABORT, 'protocol_records are immutable'); END;
-- Permanent deletion of a research stays the sole authorized exception, as it is for step inputs (migration 0010).
CREATE TRIGGER protocol_records_no_delete BEFORE DELETE ON protocol_records
WHEN NOT EXISTS (SELECT 1 FROM research_purge_authorizations WHERE research_id = OLD.research_id)
BEGIN SELECT RAISE(ABORT, 'protocol_records are immutable'); END;

-- Existing researches keep the workflow they ran under; a research never changes workflow after it is opened.
ALTER TABLE scope_revisions ADD COLUMN search_workflow TEXT NOT NULL DEFAULT 'legacy'
  CHECK (search_workflow IN ('legacy', 'sw'));
-- Audit digests. Steps opened before the protocol was frozen keep a NULL hash.
ALTER TABLE run_steps ADD COLUMN protocol_hash TEXT;
ALTER TABLE step_inputs ADD COLUMN payload_sha256 TEXT;
ALTER TABLE model_sessions ADD COLUMN output_sha256 TEXT;
ALTER TABLE search_runs ADD COLUMN payload_sha256 TEXT;
