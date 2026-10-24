-- deixis:foreign-keys-off
-- Citation snowballing (plan .local/plans/snowballing-plan.md). `runs.kind` gains `snowball`, one round of a series
-- the person starts from chosen works; `runs` is rebuilt exactly as 0002 did (SQLite cannot change a CHECK in place):
-- every row copied unchanged, every earlier kind kept, the three triggers and the index recreated with the same text.
CREATE TABLE runs_new (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  scope_revision INTEGER NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('discovery', 'answer', 'answer_review', 'followup_answer', 'table_columns', 'table_fill', 'cell_recheck', 'table_column_recheck', 'screen_more', 'research_title', 'pdf_collection', 'pdf_ocr', 'report', 'fulltext_fetch', 'fulltext_adjudication', 'lineage_links', 'claim_decomposition', 'kill_search', 'review', 'watch_check', 'citation_map', 'citation_check', 'snowball')),
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

-- What each OpenAlex identity a round's request returned became, written in the transaction that stores the request's
-- records and marks its step succeeded, so "new in this round" is read from here and never derived again from the
-- research's membership after the fact (a crash between the requests and the round's list would make the round's own
-- finds look old). `new`: the work first joined the research here; `seen`: a work this round already brought;
-- `existing`: a work the research held (or the person removed) before; `ambiguous`: the id names more than one local
-- work, nothing written; `no_record`: OpenAlex answered completely and has no record of an id that was asked for;
-- `unresolved`: an asked id the answer did not account for (incomplete answer or a dropped record).
CREATE TABLE snowball_admissions (
  run_id TEXT NOT NULL REFERENCES runs(id),
  request_index INTEGER NOT NULL,
  position INTEGER NOT NULL,
  openalex_id TEXT NOT NULL,
  outcome TEXT NOT NULL CHECK (outcome IN ('new', 'seen', 'existing', 'ambiguous', 'no_record', 'unresolved')),
  work_id TEXT,
  source_version_id TEXT REFERENCES source_versions(id),
  PRIMARY KEY (run_id, request_index, openalex_id)
);
