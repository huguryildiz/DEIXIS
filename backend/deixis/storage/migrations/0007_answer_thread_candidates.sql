-- deixis:foreign-keys-off
-- Kill search from the answer's Next steps (D98). A candidate the person writes from an answer gets its own origin,
-- `answer_thread`: like `owner_text` it is the person's sentence with no report row, basis or fingerprint; the answer and
-- the unanswered aspect it was written beside are context, stored in `answer_candidate_links`, never the claim.
-- SQLite cannot change a CHECK in place, so `research_candidates` is rebuilt as 0002 rebuilt `runs` (SQLite's 12-step
-- procedure): every row is copied unchanged, the triggers that read the table are dropped and recreated around it
-- with the same text, as are its own triggers and indexes.

CREATE TABLE research_candidates_new (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  origin TEXT NOT NULL CHECK (origin IN ('report_gap', 'owner_text', 'answer_thread')),
  origin_gap_row_id TEXT, origin_report_id TEXT, gap_kind TEXT,
  origin_text TEXT NOT NULL,
  origin_basis_json TEXT NOT NULL, origin_basis_view_json TEXT NOT NULL, origin_provenance_json TEXT NOT NULL,
  origin_fingerprint TEXT,
  idempotency_key TEXT UNIQUE,
  current_version INTEGER NOT NULL DEFAULT 0 CHECK (current_version >= 0),
  trashed_at TEXT, created_at TEXT NOT NULL,
  CHECK ((origin = 'report_gap' AND origin_report_id IS NOT NULL AND origin_gap_row_id IS NOT NULL
          AND gap_kind IS NOT NULL AND origin_fingerprint IS NOT NULL)
      OR (origin IN ('owner_text', 'answer_thread') AND origin_report_id IS NULL AND origin_gap_row_id IS NULL
          AND gap_kind IS NULL AND origin_fingerprint IS NULL))
) WITHOUT ROWID;
INSERT INTO research_candidates_new SELECT * FROM research_candidates;
DROP TRIGGER candidate_status_overrides_no_delete;
DROP TRIGGER candidate_versions_no_delete;
DROP TRIGGER claim_elements_no_delete;
DROP TRIGGER claim_matrix_cells_no_delete;
DROP TRIGGER claim_matrix_evidence_no_delete;
DROP TRIGGER kill_search_hits_no_delete;
DROP TRIGGER kill_search_queries_no_delete;
DROP TRIGGER kill_search_query_records_no_delete;
DROP TRIGGER kill_searches_no_delete;
DROP TRIGGER kill_searches_run_guard;
DROP TABLE research_candidates;
ALTER TABLE research_candidates_new RENAME TO research_candidates;
CREATE UNIQUE INDEX research_candidates_gap ON research_candidates(research_id, origin_gap_row_id, origin_fingerprint)
  WHERE origin_gap_row_id IS NOT NULL;
CREATE INDEX research_candidates_research ON research_candidates(research_id, created_at, id);
CREATE TRIGGER research_candidates_empty_pointer BEFORE INSERT ON research_candidates
WHEN NEW.current_version <> 0
BEGIN SELECT RAISE(ABORT, 'candidate starts at version zero'); END;
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
CREATE TRIGGER research_candidates_no_conflicting_insert BEFORE INSERT ON research_candidates
WHEN EXISTS (SELECT 1 FROM research_candidates WHERE id = NEW.id OR (NEW.idempotency_key IS NOT NULL AND idempotency_key = NEW.idempotency_key) OR (NEW.origin_gap_row_id IS NOT NULL AND research_id = NEW.research_id AND origin_gap_row_id = NEW.origin_gap_row_id AND origin_fingerprint = NEW.origin_fingerprint))
BEGIN SELECT RAISE(ABORT, 'research_candidates already exists'); END;
CREATE TRIGGER research_candidates_no_delete BEFORE DELETE ON research_candidates
WHEN NOT EXISTS (SELECT 1 FROM research_candidates c JOIN research_purge_authorizations a ON a.research_id = c.research_id WHERE c.id = OLD.id)
BEGIN SELECT RAISE(ABORT, 'research_candidates requires research purge authorization'); END;
CREATE TRIGGER research_candidates_publish_guard BEFORE UPDATE OF current_version ON research_candidates
WHEN NEW.current_version <> OLD.current_version + 1 OR NOT EXISTS (
  SELECT 1 FROM candidate_versions v WHERE v.candidate_id = OLD.id AND v.version = NEW.current_version)
BEGIN SELECT RAISE(ABORT, 'candidate pointer needs its next existing version'); END;
CREATE TRIGGER candidate_status_overrides_no_delete BEFORE DELETE ON candidate_status_overrides
WHEN NOT EXISTS (SELECT 1 FROM research_candidates c JOIN research_purge_authorizations a ON a.research_id = c.research_id JOIN candidate_versions v ON v.candidate_id = c.id WHERE v.id = OLD.candidate_version_id)
BEGIN SELECT RAISE(ABORT, 'candidate_status_overrides requires research purge authorization'); END;
CREATE TRIGGER candidate_versions_no_delete BEFORE DELETE ON candidate_versions
WHEN NOT EXISTS (SELECT 1 FROM research_candidates c JOIN research_purge_authorizations a ON a.research_id = c.research_id WHERE c.id = OLD.candidate_id)
BEGIN SELECT RAISE(ABORT, 'candidate_versions requires research purge authorization'); END;
CREATE TRIGGER claim_elements_no_delete BEFORE DELETE ON claim_elements
WHEN NOT EXISTS (SELECT 1 FROM research_candidates c JOIN research_purge_authorizations a ON a.research_id = c.research_id JOIN candidate_versions v ON v.candidate_id = c.id WHERE v.id = OLD.candidate_version_id)
BEGIN SELECT RAISE(ABORT, 'claim_elements requires research purge authorization'); END;
CREATE TRIGGER claim_matrix_cells_no_delete BEFORE DELETE ON claim_matrix_cells
WHEN NOT EXISTS (SELECT 1 FROM research_candidates c JOIN research_purge_authorizations a ON a.research_id = c.research_id JOIN candidate_versions v ON v.candidate_id = c.id JOIN kill_searches s ON s.candidate_version_id = v.id WHERE s.id = OLD.kill_search_id)
BEGIN SELECT RAISE(ABORT, 'claim_matrix_cells requires research purge authorization'); END;
CREATE TRIGGER claim_matrix_evidence_no_delete BEFORE DELETE ON claim_matrix_evidence
WHEN NOT EXISTS (SELECT 1 FROM research_candidates c JOIN research_purge_authorizations a ON a.research_id = c.research_id JOIN candidate_versions v ON v.candidate_id = c.id JOIN kill_searches s ON s.candidate_version_id = v.id WHERE s.id = OLD.kill_search_id)
BEGIN SELECT RAISE(ABORT, 'claim_matrix_evidence requires research purge authorization'); END;
CREATE TRIGGER kill_search_hits_no_delete BEFORE DELETE ON kill_search_hits
WHEN NOT EXISTS (SELECT 1 FROM research_candidates c JOIN research_purge_authorizations a ON a.research_id = c.research_id JOIN candidate_versions v ON v.candidate_id = c.id JOIN kill_searches s ON s.candidate_version_id = v.id WHERE s.id = OLD.kill_search_id)
BEGIN SELECT RAISE(ABORT, 'kill_search_hits requires research purge authorization'); END;
CREATE TRIGGER kill_search_queries_no_delete BEFORE DELETE ON kill_search_queries
WHEN NOT EXISTS (SELECT 1 FROM research_candidates c JOIN research_purge_authorizations a ON a.research_id = c.research_id JOIN candidate_versions v ON v.candidate_id = c.id JOIN kill_searches s ON s.candidate_version_id = v.id WHERE s.id = OLD.kill_search_id)
BEGIN SELECT RAISE(ABORT, 'kill_search_queries requires research purge authorization'); END;
CREATE TRIGGER kill_search_query_records_no_delete BEFORE DELETE ON kill_search_query_records
WHEN NOT EXISTS (SELECT 1 FROM research_candidates c JOIN research_purge_authorizations a ON a.research_id = c.research_id JOIN candidate_versions v ON v.candidate_id = c.id JOIN kill_searches s ON s.candidate_version_id = v.id WHERE s.id = OLD.kill_search_id)
BEGIN SELECT RAISE(ABORT, 'kill_search_query_records requires research purge authorization'); END;
CREATE TRIGGER kill_searches_no_delete BEFORE DELETE ON kill_searches
WHEN NOT EXISTS (SELECT 1 FROM research_candidates c JOIN research_purge_authorizations a ON a.research_id = c.research_id JOIN candidate_versions v ON v.candidate_id = c.id WHERE v.id = OLD.candidate_version_id)
BEGIN SELECT RAISE(ABORT, 'kill_searches requires research purge authorization'); END;
CREATE TRIGGER kill_searches_run_guard BEFORE INSERT ON kill_searches
WHEN NOT EXISTS (
 SELECT 1 FROM runs r JOIN candidate_versions v ON v.id = NEW.candidate_version_id
 JOIN research_candidates c ON c.id = v.candidate_id WHERE r.id = NEW.run_id AND r.kind = 'kill_search' AND r.research_id = c.research_id)
BEGIN SELECT RAISE(ABORT, 'kill-search run kind or research mismatch'); END;

-- One row per candidate written from an answer: the answer it was written under and, when the person wrote it beside one
-- of the answer's unanswered aspects, that aspect's index in the answer's stored draft. A second write from the same
-- aspect of the same answer finds this row and opens the same candidate; a candidate from the generic row has no aspect.
CREATE TABLE answer_candidate_links (
  candidate_id TEXT PRIMARY KEY REFERENCES research_candidates(id),
  research_id TEXT NOT NULL REFERENCES researches(id),
  answer_id TEXT NOT NULL REFERENCES answers(id),
  aspect_index INTEGER CHECK (aspect_index IS NULL OR (typeof(aspect_index) = 'integer' AND aspect_index >= 0)),
  created_at TEXT NOT NULL
) WITHOUT ROWID;
CREATE UNIQUE INDEX answer_candidate_links_aspect ON answer_candidate_links(answer_id, aspect_index)
  WHERE aspect_index IS NOT NULL;
CREATE INDEX answer_candidate_links_answer ON answer_candidate_links(research_id, answer_id, created_at);
CREATE TRIGGER answer_candidate_links_no_conflicting_insert BEFORE INSERT ON answer_candidate_links
WHEN EXISTS (SELECT 1 FROM answer_candidate_links WHERE candidate_id = NEW.candidate_id
             OR (NEW.aspect_index IS NOT NULL AND answer_id = NEW.answer_id AND aspect_index = NEW.aspect_index))
BEGIN SELECT RAISE(ABORT, 'answer_candidate_links already exists'); END;
CREATE TRIGGER answer_candidate_links_integrity BEFORE INSERT ON answer_candidate_links
WHEN NOT EXISTS (SELECT 1 FROM research_candidates c JOIN answers a ON a.research_id = c.research_id
                 WHERE c.id = NEW.candidate_id AND c.origin = 'answer_thread' AND c.research_id = NEW.research_id
                   AND a.id = NEW.answer_id)
BEGIN SELECT RAISE(ABORT, 'answer link needs an answer-thread candidate and an answer of its research'); END;
CREATE TRIGGER answer_candidate_links_no_update BEFORE UPDATE ON answer_candidate_links
BEGIN SELECT RAISE(ABORT, 'answer_candidate_links is immutable'); END;
CREATE TRIGGER answer_candidate_links_no_delete BEFORE DELETE ON answer_candidate_links
WHEN NOT EXISTS (SELECT 1 FROM research_purge_authorizations a WHERE a.research_id = OLD.research_id)
BEGIN SELECT RAISE(ABORT, 'answer_candidate_links requires research purge authorization'); END;
