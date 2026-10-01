-- deixis:foreign-keys-off
-- Candidate runs carry {"candidate_id", "candidate_version_id", ...}; K3 defines the remaining target fields.
CREATE TABLE runs_new (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  scope_revision INTEGER NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('discovery', 'answer', 'table_columns', 'table_fill', 'cell_recheck', 'research_title', 'pdf_collection', 'pdf_ocr', 'report', 'fulltext_fetch', 'fulltext_adjudication', 'lineage_links', 'claim_decomposition', 'kill_search')),
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
DROP TABLE runs;
ALTER TABLE runs_new RENAME TO runs;
CREATE INDEX runs_status ON runs(status, created_at);

CREATE TABLE research_candidates (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  origin TEXT NOT NULL CHECK (origin IN ('report_gap', 'owner_text')),
  origin_gap_row_id TEXT, origin_report_id TEXT, gap_kind TEXT,
  origin_text TEXT NOT NULL,
  origin_basis_json TEXT NOT NULL, origin_basis_view_json TEXT NOT NULL, origin_provenance_json TEXT NOT NULL,
  origin_fingerprint TEXT,
  idempotency_key TEXT UNIQUE,
  current_version INTEGER NOT NULL DEFAULT 0 CHECK (current_version >= 0),
  trashed_at TEXT, created_at TEXT NOT NULL,
  CHECK ((origin = 'report_gap' AND origin_report_id IS NOT NULL AND origin_gap_row_id IS NOT NULL
          AND gap_kind IS NOT NULL AND origin_fingerprint IS NOT NULL)
      OR (origin = 'owner_text' AND origin_report_id IS NULL AND origin_gap_row_id IS NULL
          AND gap_kind IS NULL AND origin_fingerprint IS NULL))
) WITHOUT ROWID;
CREATE UNIQUE INDEX research_candidates_gap ON research_candidates(research_id, origin_gap_row_id, origin_fingerprint)
  WHERE origin_gap_row_id IS NOT NULL;
CREATE INDEX research_candidates_research ON research_candidates(research_id, created_at, id);
CREATE TABLE candidate_versions (
  id TEXT PRIMARY KEY,
  candidate_id TEXT NOT NULL REFERENCES research_candidates(id),
  version INTEGER NOT NULL CHECK (version >= 1),
  claim_statement TEXT NOT NULL CHECK (length(trim(claim_statement)) > 0),
  conditions_json TEXT NOT NULL,
  nearest_simple_explanation TEXT, critical_assumption TEXT NOT NULL, validation_plan TEXT NOT NULL,
  origin TEXT NOT NULL CHECK (origin IN ('model_decomposition', 'human_edit')),
  step_input_id TEXT REFERENCES step_inputs(id),
  idempotency_key TEXT UNIQUE,
  created_at TEXT NOT NULL,
  UNIQUE (candidate_id, version),
  CHECK ((origin = 'model_decomposition') = (step_input_id IS NOT NULL))
) WITHOUT ROWID;
CREATE TABLE claim_elements (
  id TEXT PRIMARY KEY,
  candidate_version_id TEXT NOT NULL REFERENCES candidate_versions(id),
  position INTEGER NOT NULL CHECK (position >= 1),
  text TEXT NOT NULL CHECK (length(trim(text)) > 0),
  kind TEXT NOT NULL CHECK (kind IN ('mechanism', 'condition', 'outcome', 'parameter')),
  UNIQUE (candidate_version_id, position)
) WITHOUT ROWID;
CREATE TABLE kill_searches (
  id TEXT PRIMARY KEY,
  candidate_version_id TEXT NOT NULL REFERENCES candidate_versions(id),
  run_id TEXT NOT NULL UNIQUE REFERENCES runs(id),
  query_block_json TEXT NOT NULL, rendered_queries_json TEXT NOT NULL, skipped_terms_json TEXT NOT NULL, selection_json TEXT NOT NULL,
  outcome TEXT NOT NULL CHECK (outcome IN ('running', 'paused', 'completed', 'failed', 'stopped')),
  found INTEGER NOT NULL DEFAULT 0 CHECK (found >= 0),
  kept INTEGER NOT NULL DEFAULT 0 CHECK (kept >= 0 AND kept <= 8),
  rank_cut INTEGER NOT NULL DEFAULT 0 CHECK (rank_cut >= 0),
  duplicates INTEGER NOT NULL DEFAULT 0 CHECK (duplicates >= 0),
  -- An empty merge must be distinguishable from a merge not yet recorded.
  hits_recorded INTEGER NOT NULL DEFAULT 0 CHECK (hits_recorded IN (0, 1)),
  created_at TEXT NOT NULL
) WITHOUT ROWID;
CREATE INDEX kill_searches_version ON kill_searches(candidate_version_id, created_at, id);
CREATE TABLE kill_search_queries (
  kill_search_id TEXT NOT NULL REFERENCES kill_searches(id),
  position INTEGER NOT NULL CHECK (position >= 1),
  status TEXT NOT NULL CHECK (status IN ('succeeded', 'failed', 'outcome_unknown')),
  provider TEXT NOT NULL, query_text TEXT NOT NULL,
  record_count INTEGER NOT NULL CHECK (record_count >= 0),
  error_code TEXT, raw_payload_path TEXT, payload_sha256 TEXT, records_sha256 TEXT NOT NULL,
  step_id TEXT REFERENCES run_steps(id),
  PRIMARY KEY (kill_search_id, position),
  CHECK (status = 'succeeded' OR record_count = 0)
) WITHOUT ROWID;
CREATE TABLE kill_search_query_records (
  kill_search_id TEXT NOT NULL REFERENCES kill_searches(id),
  position INTEGER NOT NULL CHECK (position >= 1),
  rank INTEGER NOT NULL CHECK (rank >= 1),
  provider TEXT NOT NULL, source_version_id TEXT NOT NULL REFERENCES source_versions(id), work_id TEXT,
  PRIMARY KEY (kill_search_id, position, rank),
  FOREIGN KEY (kill_search_id, position) REFERENCES kill_search_queries(kill_search_id, position)
) WITHOUT ROWID;
CREATE INDEX kill_search_query_records_source ON kill_search_query_records(source_version_id);
CREATE TABLE kill_search_hits (
  kill_search_id TEXT NOT NULL REFERENCES kill_searches(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  work_id TEXT,
  rank_key INTEGER NOT NULL CHECK (rank_key >= 1),
  kept INTEGER NOT NULL CHECK (kept IN (0, 1)),
  cut_reason TEXT CHECK (cut_reason IS NULL OR cut_reason IN ('rank_cut')),
  reading_depth TEXT CHECK (reading_depth IS NULL OR reading_depth IN ('abstract', 'stored_passages', 'metadata_only')),
  assessment_state TEXT CHECK (assessment_state IS NULL OR assessment_state IN ('pending', 'assessed', 'insufficient_access', 'not_assessed_budget')),
  work_relevance TEXT CHECK (work_relevance IS NULL OR work_relevance IN ('unrelated', 'related', 'uncertain')),
  states_whole_claim INTEGER CHECK (states_whole_claim IS NULL OR states_whole_claim IN (0, 1)),
  note TEXT, step_input_id TEXT REFERENCES step_inputs(id),
  PRIMARY KEY (kill_search_id, source_version_id),
  CHECK ((kept = 0 AND cut_reason IS NOT NULL AND reading_depth IS NULL AND assessment_state IS NULL
          AND work_relevance IS NULL AND states_whole_claim IS NULL AND note IS NULL AND step_input_id IS NULL)
      OR (kept = 1 AND cut_reason IS NULL AND reading_depth IS NOT NULL AND assessment_state IS NOT NULL)),
  CHECK ((assessment_state IS 'assessed' AND work_relevance IS NOT NULL
          AND states_whole_claim IS NOT NULL AND step_input_id IS NOT NULL)
      OR (assessment_state IS NOT 'assessed' AND work_relevance IS NULL
          AND states_whole_claim IS NULL AND note IS NULL AND step_input_id IS NULL))
) WITHOUT ROWID;
CREATE INDEX kill_search_hits_source ON kill_search_hits(source_version_id);
CREATE TABLE claim_matrix_cells (
  id TEXT PRIMARY KEY,
  kill_search_id TEXT NOT NULL REFERENCES kill_searches(id),
  element_id TEXT NOT NULL REFERENCES claim_elements(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  relation TEXT NOT NULL CHECK (relation IN ('explicit_support', 'reasoned_inference', 'partial_match', 'no_match_in_supplied_text', 'uncertain')),
  condition_alignment TEXT CHECK (condition_alignment IS NULL OR condition_alignment IN ('aligned', 'different_conditions', 'unclear')),
  note TEXT,
  UNIQUE (kill_search_id, element_id, source_version_id),
  CHECK ((relation IN ('explicit_support', 'reasoned_inference', 'partial_match') AND condition_alignment IS NOT NULL)
      OR (relation = 'no_match_in_supplied_text' AND condition_alignment IS NULL) OR relation = 'uncertain')
) WITHOUT ROWID;
CREATE INDEX claim_matrix_cells_source ON claim_matrix_cells(source_version_id);
CREATE TABLE claim_matrix_evidence (
  id TEXT PRIMARY KEY,
  kill_search_id TEXT NOT NULL REFERENCES kill_searches(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  element_id TEXT REFERENCES claim_elements(id),
  matrix_cell_id TEXT REFERENCES claim_matrix_cells(id),
  evidence_kind TEXT NOT NULL CHECK (evidence_kind IN ('abstract', 'passage')),
  passage_id TEXT REFERENCES passages(id),
  quote TEXT NOT NULL CHECK (length(trim(quote)) > 0),
  CHECK ((element_id IS NULL) = (matrix_cell_id IS NULL)),
  CHECK ((evidence_kind = 'passage') = (passage_id IS NOT NULL))
) WITHOUT ROWID;
CREATE INDEX claim_matrix_evidence_search ON claim_matrix_evidence(kill_search_id, source_version_id);
CREATE INDEX claim_matrix_evidence_passage ON claim_matrix_evidence(passage_id);
CREATE INDEX claim_matrix_evidence_source ON claim_matrix_evidence(source_version_id);
CREATE TABLE candidate_status_overrides (
  id TEXT PRIMARY KEY,
  candidate_version_id TEXT NOT NULL REFERENCES candidate_versions(id),
  status TEXT NOT NULL CHECK (status IN ('not_run', 'undecided', 'narrowed', 'closed', 'open')),
  reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
  created_at TEXT NOT NULL
) WITHOUT ROWID;
CREATE INDEX candidate_status_overrides_version ON candidate_status_overrides(candidate_version_id, created_at, id);

CREATE TRIGGER research_candidates_no_conflicting_insert BEFORE INSERT ON research_candidates
WHEN EXISTS (SELECT 1 FROM research_candidates WHERE id = NEW.id OR (NEW.idempotency_key IS NOT NULL AND idempotency_key = NEW.idempotency_key) OR (NEW.origin_gap_row_id IS NOT NULL AND research_id = NEW.research_id AND origin_gap_row_id = NEW.origin_gap_row_id AND origin_fingerprint = NEW.origin_fingerprint))
BEGIN SELECT RAISE(ABORT, 'research_candidates already exists'); END;
CREATE TRIGGER research_candidates_no_delete BEFORE DELETE ON research_candidates
WHEN NOT EXISTS (SELECT 1 FROM research_candidates c JOIN research_purge_authorizations a ON a.research_id = c.research_id WHERE c.id = OLD.id)
BEGIN SELECT RAISE(ABORT, 'research_candidates requires research purge authorization'); END;

CREATE TRIGGER candidate_versions_no_conflicting_insert BEFORE INSERT ON candidate_versions
WHEN EXISTS (SELECT 1 FROM candidate_versions WHERE id = NEW.id OR (candidate_id = NEW.candidate_id AND version = NEW.version) OR (NEW.idempotency_key IS NOT NULL AND idempotency_key = NEW.idempotency_key))
BEGIN SELECT RAISE(ABORT, 'candidate_versions already exists'); END;
CREATE TRIGGER candidate_versions_no_delete BEFORE DELETE ON candidate_versions
WHEN NOT EXISTS (SELECT 1 FROM research_candidates c JOIN research_purge_authorizations a ON a.research_id = c.research_id WHERE c.id = OLD.candidate_id)
BEGIN SELECT RAISE(ABORT, 'candidate_versions requires research purge authorization'); END;
CREATE TRIGGER candidate_versions_no_update BEFORE UPDATE ON candidate_versions
BEGIN SELECT RAISE(ABORT, 'candidate_versions is immutable'); END;

CREATE TRIGGER claim_elements_no_conflicting_insert BEFORE INSERT ON claim_elements
WHEN EXISTS (SELECT 1 FROM claim_elements WHERE id = NEW.id OR (candidate_version_id = NEW.candidate_version_id AND position = NEW.position))
BEGIN SELECT RAISE(ABORT, 'claim_elements already exists'); END;
CREATE TRIGGER claim_elements_no_delete BEFORE DELETE ON claim_elements
WHEN NOT EXISTS (SELECT 1 FROM research_candidates c JOIN research_purge_authorizations a ON a.research_id = c.research_id JOIN candidate_versions v ON v.candidate_id = c.id WHERE v.id = OLD.candidate_version_id)
BEGIN SELECT RAISE(ABORT, 'claim_elements requires research purge authorization'); END;
CREATE TRIGGER claim_elements_no_update BEFORE UPDATE ON claim_elements
BEGIN SELECT RAISE(ABORT, 'claim_elements is immutable'); END;

CREATE TRIGGER kill_searches_no_conflicting_insert BEFORE INSERT ON kill_searches
WHEN EXISTS (SELECT 1 FROM kill_searches WHERE id = NEW.id OR run_id = NEW.run_id)
BEGIN SELECT RAISE(ABORT, 'kill_searches already exists'); END;
CREATE TRIGGER kill_searches_no_delete BEFORE DELETE ON kill_searches
WHEN NOT EXISTS (SELECT 1 FROM research_candidates c JOIN research_purge_authorizations a ON a.research_id = c.research_id JOIN candidate_versions v ON v.candidate_id = c.id WHERE v.id = OLD.candidate_version_id)
BEGIN SELECT RAISE(ABORT, 'kill_searches requires research purge authorization'); END;

CREATE TRIGGER kill_search_queries_no_conflicting_insert BEFORE INSERT ON kill_search_queries
WHEN EXISTS (SELECT 1 FROM kill_search_queries WHERE kill_search_id = NEW.kill_search_id AND position = NEW.position)
BEGIN SELECT RAISE(ABORT, 'kill_search_queries already exists'); END;
CREATE TRIGGER kill_search_queries_no_delete BEFORE DELETE ON kill_search_queries
WHEN NOT EXISTS (SELECT 1 FROM research_candidates c JOIN research_purge_authorizations a ON a.research_id = c.research_id JOIN candidate_versions v ON v.candidate_id = c.id JOIN kill_searches s ON s.candidate_version_id = v.id WHERE s.id = OLD.kill_search_id)
BEGIN SELECT RAISE(ABORT, 'kill_search_queries requires research purge authorization'); END;
CREATE TRIGGER kill_search_queries_no_update BEFORE UPDATE ON kill_search_queries
BEGIN SELECT RAISE(ABORT, 'kill_search_queries is immutable'); END;

CREATE TRIGGER kill_search_query_records_no_conflicting_insert BEFORE INSERT ON kill_search_query_records
WHEN EXISTS (SELECT 1 FROM kill_search_query_records WHERE kill_search_id = NEW.kill_search_id AND position = NEW.position AND rank = NEW.rank)
BEGIN SELECT RAISE(ABORT, 'kill_search_query_records already exists'); END;
CREATE TRIGGER kill_search_query_records_no_delete BEFORE DELETE ON kill_search_query_records
WHEN NOT EXISTS (SELECT 1 FROM research_candidates c JOIN research_purge_authorizations a ON a.research_id = c.research_id JOIN candidate_versions v ON v.candidate_id = c.id JOIN kill_searches s ON s.candidate_version_id = v.id WHERE s.id = OLD.kill_search_id)
BEGIN SELECT RAISE(ABORT, 'kill_search_query_records requires research purge authorization'); END;
CREATE TRIGGER kill_search_query_records_no_update BEFORE UPDATE ON kill_search_query_records
BEGIN SELECT RAISE(ABORT, 'kill_search_query_records is immutable'); END;

CREATE TRIGGER kill_search_hits_no_conflicting_insert BEFORE INSERT ON kill_search_hits
WHEN EXISTS (SELECT 1 FROM kill_search_hits WHERE kill_search_id = NEW.kill_search_id AND source_version_id = NEW.source_version_id)
BEGIN SELECT RAISE(ABORT, 'kill_search_hits already exists'); END;
CREATE TRIGGER kill_search_hits_no_delete BEFORE DELETE ON kill_search_hits
WHEN NOT EXISTS (SELECT 1 FROM research_candidates c JOIN research_purge_authorizations a ON a.research_id = c.research_id JOIN candidate_versions v ON v.candidate_id = c.id JOIN kill_searches s ON s.candidate_version_id = v.id WHERE s.id = OLD.kill_search_id)
BEGIN SELECT RAISE(ABORT, 'kill_search_hits requires research purge authorization'); END;

CREATE TRIGGER claim_matrix_cells_no_conflicting_insert BEFORE INSERT ON claim_matrix_cells
WHEN EXISTS (SELECT 1 FROM claim_matrix_cells WHERE id = NEW.id OR (kill_search_id = NEW.kill_search_id AND element_id = NEW.element_id AND source_version_id = NEW.source_version_id))
BEGIN SELECT RAISE(ABORT, 'claim_matrix_cells already exists'); END;
CREATE TRIGGER claim_matrix_cells_no_delete BEFORE DELETE ON claim_matrix_cells
WHEN NOT EXISTS (SELECT 1 FROM research_candidates c JOIN research_purge_authorizations a ON a.research_id = c.research_id JOIN candidate_versions v ON v.candidate_id = c.id JOIN kill_searches s ON s.candidate_version_id = v.id WHERE s.id = OLD.kill_search_id)
BEGIN SELECT RAISE(ABORT, 'claim_matrix_cells requires research purge authorization'); END;
CREATE TRIGGER claim_matrix_cells_no_update BEFORE UPDATE ON claim_matrix_cells
BEGIN SELECT RAISE(ABORT, 'claim_matrix_cells is immutable'); END;

CREATE TRIGGER claim_matrix_evidence_no_conflicting_insert BEFORE INSERT ON claim_matrix_evidence
WHEN EXISTS (SELECT 1 FROM claim_matrix_evidence WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'claim_matrix_evidence already exists'); END;
CREATE TRIGGER claim_matrix_evidence_no_delete BEFORE DELETE ON claim_matrix_evidence
WHEN NOT EXISTS (SELECT 1 FROM research_candidates c JOIN research_purge_authorizations a ON a.research_id = c.research_id JOIN candidate_versions v ON v.candidate_id = c.id JOIN kill_searches s ON s.candidate_version_id = v.id WHERE s.id = OLD.kill_search_id)
BEGIN SELECT RAISE(ABORT, 'claim_matrix_evidence requires research purge authorization'); END;
CREATE TRIGGER claim_matrix_evidence_no_update BEFORE UPDATE ON claim_matrix_evidence
BEGIN SELECT RAISE(ABORT, 'claim_matrix_evidence is immutable'); END;

CREATE TRIGGER candidate_status_overrides_no_conflicting_insert BEFORE INSERT ON candidate_status_overrides
WHEN EXISTS (SELECT 1 FROM candidate_status_overrides WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'candidate_status_overrides already exists'); END;
CREATE TRIGGER candidate_status_overrides_no_delete BEFORE DELETE ON candidate_status_overrides
WHEN NOT EXISTS (SELECT 1 FROM research_candidates c JOIN research_purge_authorizations a ON a.research_id = c.research_id JOIN candidate_versions v ON v.candidate_id = c.id WHERE v.id = OLD.candidate_version_id)
BEGIN SELECT RAISE(ABORT, 'candidate_status_overrides requires research purge authorization'); END;
CREATE TRIGGER candidate_status_overrides_no_update BEFORE UPDATE ON candidate_status_overrides
BEGIN SELECT RAISE(ABORT, 'candidate_status_overrides is immutable'); END;
CREATE TRIGGER research_candidates_identity_no_update BEFORE UPDATE ON research_candidates
WHEN NEW.id IS NOT OLD.id
 OR NEW.research_id IS NOT OLD.research_id
 OR NEW.origin IS NOT OLD.origin
 OR NEW.origin_gap_row_id IS NOT OLD.origin_gap_row_id
 OR NEW.origin_report_id IS NOT OLD.origin_report_id
 OR NEW.gap_kind IS NOT OLD.gap_kind
 OR NEW.origin_text IS NOT OLD.origin_text
 OR NEW.origin_basis_json IS NOT OLD.origin_basis_json
 OR NEW.origin_basis_view_json IS NOT OLD.origin_basis_view_json
 OR NEW.origin_provenance_json IS NOT OLD.origin_provenance_json
 OR NEW.origin_fingerprint IS NOT OLD.origin_fingerprint
 OR NEW.idempotency_key IS NOT OLD.idempotency_key
 OR NEW.created_at IS NOT OLD.created_at
BEGIN SELECT RAISE(ABORT, 'research_candidates frozen columns are immutable'); END;
CREATE TRIGGER research_candidates_empty_pointer BEFORE INSERT ON research_candidates
WHEN NEW.current_version <> 0
BEGIN SELECT RAISE(ABORT, 'candidate starts at version zero'); END;
CREATE TRIGGER research_candidates_publish_guard BEFORE UPDATE OF current_version ON research_candidates
WHEN NEW.current_version <> OLD.current_version + 1 OR NOT EXISTS (
  SELECT 1 FROM candidate_versions v WHERE v.candidate_id = OLD.id AND v.version = NEW.current_version)
BEGIN SELECT RAISE(ABORT, 'candidate pointer needs its next existing version'); END;
CREATE TRIGGER kill_searches_run_guard BEFORE INSERT ON kill_searches
WHEN NOT EXISTS (
 SELECT 1 FROM runs r JOIN candidate_versions v ON v.id = NEW.candidate_version_id
 JOIN research_candidates c ON c.id = v.candidate_id WHERE r.id = NEW.run_id AND r.kind = 'kill_search' AND r.research_id = c.research_id)
BEGIN SELECT RAISE(ABORT, 'kill-search run kind or research mismatch'); END;
CREATE TRIGGER kill_searches_identity_no_update BEFORE UPDATE ON kill_searches
WHEN NEW.id IS NOT OLD.id
 OR NEW.candidate_version_id IS NOT OLD.candidate_version_id
 OR NEW.run_id IS NOT OLD.run_id
 OR NEW.query_block_json IS NOT OLD.query_block_json
 OR NEW.rendered_queries_json IS NOT OLD.rendered_queries_json
 OR NEW.skipped_terms_json IS NOT OLD.skipped_terms_json
 OR NEW.selection_json IS NOT OLD.selection_json
 OR NEW.created_at IS NOT OLD.created_at
BEGIN SELECT RAISE(ABORT, 'kill_searches frozen columns are immutable'); END;
CREATE TRIGGER kill_searches_outcome_guard BEFORE UPDATE OF outcome ON kill_searches
WHEN NEW.outcome IS NOT OLD.outcome AND NOT (
 (OLD.outcome = 'running' AND NEW.outcome IN ('paused', 'completed', 'failed', 'stopped'))
 OR (OLD.outcome = 'paused' AND NEW.outcome IN ('running', 'completed', 'failed', 'stopped')))
BEGIN SELECT RAISE(ABORT, 'kill-search outcome is terminal'); END;
CREATE TRIGGER kill_searches_counts_guard BEFORE UPDATE OF found, kept, rank_cut, duplicates, hits_recorded ON kill_searches
WHEN OLD.outcome IN ('completed', 'failed', 'stopped')
BEGIN SELECT RAISE(ABORT, 'terminal kill-search counts are frozen'); END;
CREATE TRIGGER kill_search_hits_identity_no_update BEFORE UPDATE ON kill_search_hits
WHEN NEW.kill_search_id IS NOT OLD.kill_search_id
 OR NEW.source_version_id IS NOT OLD.source_version_id
 OR NEW.work_id IS NOT OLD.work_id
 OR NEW.rank_key IS NOT OLD.rank_key
 OR NEW.kept IS NOT OLD.kept
 OR NEW.cut_reason IS NOT OLD.cut_reason
 OR NEW.reading_depth IS NOT OLD.reading_depth
BEGIN SELECT RAISE(ABORT, 'kill_search_hits frozen columns are immutable'); END;
CREATE TRIGGER kill_search_hits_assessment_guard BEFORE UPDATE ON kill_search_hits
WHEN OLD.assessment_state IS NOT 'pending' OR NEW.assessment_state NOT IN ('assessed', 'insufficient_access', 'not_assessed_budget')
BEGIN SELECT RAISE(ABORT, 'hit assessment may be published only once'); END;
CREATE TRIGGER claim_matrix_cells_integrity BEFORE INSERT ON claim_matrix_cells
WHEN NOT EXISTS (
 SELECT 1 FROM kill_searches s JOIN claim_elements e ON e.candidate_version_id = s.candidate_version_id
 JOIN kill_search_hits h ON h.kill_search_id = s.id AND h.source_version_id = NEW.source_version_id
 WHERE s.id = NEW.kill_search_id AND e.id = NEW.element_id AND h.kept = 1 AND h.assessment_state = 'assessed')
BEGIN SELECT RAISE(ABORT, 'cell needs its version element and kept assessed hit'); END;
CREATE TRIGGER claim_matrix_evidence_integrity BEFORE INSERT ON claim_matrix_evidence
WHEN (NEW.element_id IS NOT NULL AND NOT EXISTS (
 SELECT 1 FROM claim_matrix_cells c WHERE c.id = NEW.matrix_cell_id AND c.kill_search_id = NEW.kill_search_id
 AND c.source_version_id = NEW.source_version_id AND c.element_id = NEW.element_id))
 OR (NEW.element_id IS NULL AND NOT EXISTS (
 SELECT 1 FROM kill_search_hits h WHERE h.kill_search_id = NEW.kill_search_id AND h.source_version_id = NEW.source_version_id
 AND h.kept = 1 AND h.assessment_state = 'assessed' AND h.states_whole_claim = 1))
 OR (NEW.evidence_kind = 'passage' AND NEW.passage_id IS NOT NULL AND NEW.source_version_id IS NOT (
 SELECT source_version_id FROM passages WHERE id = NEW.passage_id))
BEGIN SELECT RAISE(ABORT, 'candidate evidence scope or passage source mismatch'); END;
