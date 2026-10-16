-- deixis:foreign-keys-off
-- Citation map reading (slice 2 of the citation map): a person asks a `citation_map` run to fill what the map is
-- missing (OpenAlex records of works that have none, unread reference lists, the outside works' titles). SQLite cannot
-- change a CHECK in place, so `runs` is rebuilt as 0007 did (SQLite's 12-step procedure): every row is copied
-- unchanged, the list keeps every run kind of the earlier migrations, and the three triggers that read `runs` are
-- dropped and recreated around it with the same text, as is its index.
CREATE TABLE runs_new (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  scope_revision INTEGER NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('discovery', 'answer', 'answer_review', 'followup_answer', 'table_columns', 'table_fill', 'cell_recheck', 'table_column_recheck', 'screen_more', 'research_title', 'pdf_collection', 'pdf_ocr', 'report', 'fulltext_fetch', 'fulltext_adjudication', 'lineage_links', 'claim_decomposition', 'kill_search', 'review', 'watch_check', 'citation_map')),
  status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'pause_requested', 'paused', 'completed', 'failed', 'cancelled')),
  stage TEXT NOT NULL CHECK (stage IN ('intake', 'discovery', 'screening', 'inspection', 'answer', 'extraction', 'synthesis', 'candidate', 'claim_check', 'export')),
  pause_reason TEXT, error_json TEXT,
  budget_json TEXT NOT NULL, usage_json TEXT NOT NULL DEFAULT '{}',
  idempotency_key TEXT UNIQUE,
  target_json TEXT,
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
INSERT INTO runs_new SELECT * FROM runs;
DROP TRIGGER kill_searches_run_guard;
DROP TRIGGER owner_reviews_run_guard;
DROP TRIGGER watch_checks_run_guard;
DROP TABLE runs;
ALTER TABLE runs_new RENAME TO runs;
CREATE INDEX runs_status ON runs(status, created_at);
CREATE TRIGGER kill_searches_run_guard BEFORE INSERT ON kill_searches
WHEN NOT EXISTS (
 SELECT 1 FROM runs r JOIN candidate_versions v ON v.id = NEW.candidate_version_id
 JOIN research_candidates c ON c.id = v.candidate_id WHERE r.id = NEW.run_id AND r.kind = 'kill_search' AND r.research_id = c.research_id)
BEGIN SELECT RAISE(ABORT, 'kill-search run kind or research mismatch'); END;
CREATE TRIGGER owner_reviews_run_guard BEFORE INSERT ON owner_reviews
WHEN NOT EXISTS (SELECT 1 FROM runs WHERE id = NEW.run_id AND kind = 'review' AND research_id = NEW.research_id)
BEGIN SELECT RAISE(ABORT, 'owner review requires a review run of its research'); END;
CREATE TRIGGER watch_checks_run_guard BEFORE INSERT ON watch_checks
WHEN NOT EXISTS (SELECT 1 FROM runs WHERE id=NEW.run_id AND kind='watch_check' AND research_id=NEW.research_id)
 OR NOT EXISTS (SELECT 1 FROM watches WHERE id=NEW.watch_id AND research_id=NEW.research_id)
BEGIN SELECT RAISE(ABORT,'watch check requires its research watch and run'); END;

-- Which OpenAlex work a source version without an OpenAlex mapping is, as the citation map found it. Kept apart from
-- `identifier_mappings` on purpose: `upsert_provider_source` reuses an OpenAlex mapping, so a mapping on a person's
-- uploaded file would land every later OpenAlex hit of that work on the upload (D37 writes no mapping for the same
-- reason). Only the citation map reads this table. `method`: `record_match` is the upload's own D37 identification
-- (`record_match_json`, no request); `doi` is one OpenAlex DOI lookup. `status`: `resolved` names the work;
-- `not_found` (OpenAlex holds no work with that DOI) and `ambiguous` (more than one) name none, so a later run does not
-- ask again for the same DOI. `run_id` is the run that found it; a research purge keeps the row and clears the run.
CREATE TABLE citation_map_resolutions (
  source_version_id TEXT PRIMARY KEY REFERENCES source_versions(id) ON DELETE CASCADE,
  method TEXT NOT NULL CHECK (method IN ('record_match', 'doi')),
  status TEXT NOT NULL CHECK (status IN ('resolved', 'not_found', 'ambiguous')),
  openalex_id TEXT,
  doi TEXT,
  run_id TEXT REFERENCES runs(id) ON DELETE SET NULL,
  resolved_at TEXT NOT NULL,
  CHECK ((status = 'resolved') = (openalex_id IS NOT NULL)),
  CHECK (method <> 'doi' OR doi IS NOT NULL)
) WITHOUT ROWID;
CREATE INDEX citation_map_resolutions_openalex ON citation_map_resolutions(openalex_id);
