-- deixis:foreign-keys-off
-- Candidate runs carry {"candidate_id", "candidate_version_id", ...}; K3 defines the remaining target fields.
CREATE TABLE runs_new (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  scope_revision INTEGER NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('discovery', 'answer', 'table_columns', 'table_fill', 'cell_recheck', 'research_title', 'pdf_collection', 'pdf_ocr', 'report', 'fulltext_fetch', 'fulltext_adjudication', 'lineage_links', 'claim_decomposition', 'kill_search', 'review')),
  status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'pause_requested', 'paused', 'completed', 'failed', 'cancelled')),
  stage TEXT NOT NULL CHECK (stage IN ('intake', 'discovery', 'screening', 'inspection', 'answer', 'extraction', 'synthesis', 'candidate', 'claim_check', 'export')),
  pause_reason TEXT, error_json TEXT,
  budget_json TEXT NOT NULL, usage_json TEXT NOT NULL DEFAULT '{}',
  idempotency_key TEXT UNIQUE,
  -- Table runs: {"table_id", "column_ids", "cell_id", "include_stale"}. Report runs: {"report_id"}.
  -- Lineage runs: {"table_id", "plan_version", ...}. Candidate runs: {"candidate_id", "candidate_version_id", ...}.
  target_json TEXT,
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
INSERT INTO runs_new (id, research_id, scope_revision, kind, status, stage, pause_reason, error_json, budget_json,
                      usage_json, idempotency_key, target_json, version, created_at, updated_at)
  SELECT id, research_id, scope_revision, kind, status, stage, pause_reason, error_json, budget_json,
         usage_json, idempotency_key, target_json, version, created_at, updated_at FROM runs;
-- SQLite validates triggers on other tables during rename, even with foreign keys off.
-- Preserve the 0060 guard verbatim across the moment when runs does not exist.
DROP TRIGGER kill_searches_run_guard;
DROP TABLE runs;
ALTER TABLE runs_new RENAME TO runs;
CREATE INDEX runs_status ON runs(status, created_at);
CREATE TRIGGER kill_searches_run_guard BEFORE INSERT ON kill_searches
WHEN NOT EXISTS (
 SELECT 1 FROM runs r JOIN candidate_versions v ON v.id = NEW.candidate_version_id
 JOIN research_candidates c ON c.id = v.candidate_id WHERE r.id = NEW.run_id AND r.kind = 'kill_search' AND r.research_id = c.research_id)
BEGIN SELECT RAISE(ABORT, 'kill-search run kind or research mismatch'); END;

CREATE TABLE owner_review_snapshots (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  target_kind TEXT NOT NULL CHECK (target_kind IN ('answer', 'report', 'candidate')),
  target_id TEXT NOT NULL,
  content_json TEXT NOT NULL,
  content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64),
  markers_json TEXT NOT NULL,
  created_at TEXT NOT NULL
) WITHOUT ROWID;
CREATE TABLE owner_reviews (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  snapshot_id TEXT NOT NULL REFERENCES owner_review_snapshots(id),
  run_id TEXT NOT NULL UNIQUE REFERENCES runs(id),
  focus TEXT NOT NULL CHECK (focus IN ('source_support', 'assumptions_and_consistency')),
  -- Match Python str.strip() whitespace, including Unicode, at the SQL boundary.
  owner_note TEXT CHECK (owner_note IS NULL OR (length(owner_note) <= 500 AND length(trim(owner_note, char(9,10,11,12,13,28,29,30,31,32,133,160,5760,8192,8193,8194,8195,8196,8197,8198,8199,8200,8201,8202,8232,8233,8239,8287,12288))) > 0)),
  requested_connection TEXT NOT NULL,
  requested_model TEXT,
  requested_effort TEXT,
  failure_reason TEXT,
  sections_not_reviewed_json TEXT NOT NULL DEFAULT '[]',
  idempotency_key TEXT UNIQUE,
  created_at TEXT NOT NULL
) WITHOUT ROWID;
CREATE TABLE owner_review_findings (
  id TEXT PRIMARY KEY,
  review_id TEXT NOT NULL REFERENCES owner_reviews(id),
  ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
  finding_json TEXT NOT NULL,
  step_input_id TEXT NOT NULL REFERENCES step_inputs(id),
  UNIQUE (review_id, ordinal)
) WITHOUT ROWID;
CREATE TABLE owner_review_decisions (
  id TEXT PRIMARY KEY,
  finding_id TEXT NOT NULL REFERENCES owner_review_findings(id),
  ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
  decision TEXT NOT NULL CHECK (decision IN ('accepted', 'dismissed', 'deferred')),
  reason TEXT,
  applied_ref TEXT,
  created_at TEXT NOT NULL,
  UNIQUE (finding_id, ordinal),
  CHECK (decision != 'dismissed' OR (reason IS NOT NULL AND length(trim(reason, char(9,10,11,12,13,28,29,30,31,32,133,160,5760,8192,8193,8194,8195,8196,8197,8198,8199,8200,8201,8202,8232,8233,8239,8287,12288))) > 0)),
  CHECK (applied_ref IS NULL OR decision = 'accepted')
) WITHOUT ROWID;
CREATE INDEX owner_review_snapshots_target ON owner_review_snapshots(research_id, target_kind, target_id, created_at);
CREATE INDEX owner_reviews_research ON owner_reviews(research_id, created_at);
CREATE INDEX owner_reviews_snapshot ON owner_reviews(snapshot_id, created_at);
CREATE INDEX owner_review_findings_review ON owner_review_findings(review_id);
CREATE INDEX owner_review_decisions_finding ON owner_review_decisions(finding_id, created_at);

CREATE TRIGGER owner_reviews_run_guard BEFORE INSERT ON owner_reviews
WHEN NOT EXISTS (SELECT 1 FROM runs WHERE id = NEW.run_id AND kind = 'review' AND research_id = NEW.research_id)
BEGIN SELECT RAISE(ABORT, 'owner review requires a review run of its research'); END;
CREATE TRIGGER owner_reviews_snapshot_guard BEFORE INSERT ON owner_reviews
WHEN NOT EXISTS (SELECT 1 FROM owner_review_snapshots WHERE id = NEW.snapshot_id AND research_id = NEW.research_id)
BEGIN SELECT RAISE(ABORT, 'owner review snapshot belongs to another research'); END;
CREATE TRIGGER owner_review_findings_step_guard BEFORE INSERT ON owner_review_findings
WHEN NOT EXISTS (SELECT 1 FROM step_inputs i JOIN owner_reviews r ON r.run_id = i.run_id
                 WHERE r.id = NEW.review_id AND i.id = NEW.step_input_id AND i.research_id = r.research_id)
BEGIN SELECT RAISE(ABORT, 'finding step input belongs to another run'); END;

CREATE TRIGGER owner_review_snapshots_no_conflicting_insert BEFORE INSERT ON owner_review_snapshots
WHEN EXISTS (SELECT 1 FROM owner_review_snapshots WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'owner_review_snapshots already exists'); END;
CREATE TRIGGER owner_review_snapshots_no_delete BEFORE DELETE ON owner_review_snapshots
WHEN NOT EXISTS (SELECT 1 FROM research_purge_authorizations WHERE research_id = OLD.research_id)
BEGIN SELECT RAISE(ABORT, 'owner_review_snapshots requires research purge authorization'); END;
CREATE TRIGGER owner_review_snapshots_no_update BEFORE UPDATE ON owner_review_snapshots
BEGIN SELECT RAISE(ABORT, 'owner_review_snapshots is immutable'); END;

CREATE TRIGGER owner_reviews_no_conflicting_insert BEFORE INSERT ON owner_reviews
WHEN EXISTS (SELECT 1 FROM owner_reviews WHERE id = NEW.id OR run_id = NEW.run_id OR idempotency_key = NEW.idempotency_key)
BEGIN SELECT RAISE(ABORT, 'owner_reviews already exists'); END;
CREATE TRIGGER owner_reviews_no_delete BEFORE DELETE ON owner_reviews
WHEN NOT EXISTS (SELECT 1 FROM research_purge_authorizations WHERE research_id = OLD.research_id)
BEGIN SELECT RAISE(ABORT, 'owner_reviews requires research purge authorization'); END;
CREATE TRIGGER owner_reviews_frozen_columns BEFORE UPDATE ON owner_reviews
WHEN NEW.id IS NOT OLD.id OR NEW.research_id IS NOT OLD.research_id OR NEW.snapshot_id IS NOT OLD.snapshot_id OR NEW.run_id IS NOT OLD.run_id OR NEW.focus IS NOT OLD.focus OR NEW.owner_note IS NOT OLD.owner_note OR NEW.requested_connection IS NOT OLD.requested_connection OR NEW.requested_model IS NOT OLD.requested_model OR NEW.requested_effort IS NOT OLD.requested_effort OR NEW.idempotency_key IS NOT OLD.idempotency_key OR NEW.created_at IS NOT OLD.created_at
BEGIN SELECT RAISE(ABORT, 'owner_reviews frozen columns are immutable'); END;

CREATE TRIGGER owner_review_findings_no_conflicting_insert BEFORE INSERT ON owner_review_findings
WHEN EXISTS (SELECT 1 FROM owner_review_findings WHERE id = NEW.id OR (review_id = NEW.review_id AND ordinal = NEW.ordinal))
BEGIN SELECT RAISE(ABORT, 'owner_review_findings already exists'); END;
CREATE TRIGGER owner_review_findings_no_delete BEFORE DELETE ON owner_review_findings
WHEN NOT EXISTS (SELECT 1 FROM owner_reviews r JOIN research_purge_authorizations a ON a.research_id = r.research_id WHERE r.id = OLD.review_id)
BEGIN SELECT RAISE(ABORT, 'owner_review_findings requires research purge authorization'); END;
CREATE TRIGGER owner_review_findings_no_update BEFORE UPDATE ON owner_review_findings
BEGIN SELECT RAISE(ABORT, 'owner_review_findings is immutable'); END;

CREATE TRIGGER owner_review_decisions_no_conflicting_insert BEFORE INSERT ON owner_review_decisions
WHEN EXISTS (SELECT 1 FROM owner_review_decisions WHERE id = NEW.id OR (finding_id = NEW.finding_id AND ordinal = NEW.ordinal))
BEGIN SELECT RAISE(ABORT, 'owner_review_decisions already exists'); END;
CREATE TRIGGER owner_review_decisions_no_delete BEFORE DELETE ON owner_review_decisions
WHEN NOT EXISTS (SELECT 1 FROM owner_review_findings f JOIN owner_reviews r ON r.id = f.review_id JOIN research_purge_authorizations a ON a.research_id = r.research_id WHERE f.id = OLD.finding_id)
BEGIN SELECT RAISE(ABORT, 'owner_review_decisions requires research purge authorization'); END;
CREATE TRIGGER owner_review_decisions_no_update BEFORE UPDATE ON owner_review_decisions
BEGIN SELECT RAISE(ABORT, 'owner_review_decisions is immutable'); END;
