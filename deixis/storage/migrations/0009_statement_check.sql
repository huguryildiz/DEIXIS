-- deixis:foreign-keys-off
-- Reverse citation search, slice R1 (plan .local/plans/reverse-citation-search-plan.md). A research may have the
-- intent `statement`: its question is one sentence the person pasted, and its last step checks that sentence against
-- the works its search read instead of writing an answer. `runs.kind` gains `statement_check`. SQLite cannot change a
-- CHECK in place, so `researches` and `runs` are rebuilt as 0002 did (SQLite's 12-step procedure): every row is copied
-- unchanged, every earlier value is kept, and the three triggers that read `runs` are dropped and recreated around it
-- with the same text, as is its index. `researches` has no trigger or index of its own.
CREATE TABLE researches_new (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  current_scope_revision INTEGER NOT NULL DEFAULT 1,
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
, selection_revision INTEGER NOT NULL DEFAULT 0, trashed_at TEXT, intent TEXT NOT NULL DEFAULT 'report'
  CHECK (intent IN ('report', 'papers', 'table', 'compare', 'statement')), kind TEXT NOT NULL DEFAULT 'research' CHECK (kind IN ('research', 'citation_check')));
INSERT INTO researches_new SELECT * FROM researches;
DROP TABLE researches;
ALTER TABLE researches_new RENAME TO researches;

CREATE TABLE runs_new (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  scope_revision INTEGER NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('discovery', 'answer', 'answer_review', 'followup_answer', 'table_columns', 'table_fill', 'cell_recheck', 'table_column_recheck', 'screen_more', 'research_title', 'pdf_collection', 'pdf_ocr', 'report', 'fulltext_fetch', 'fulltext_adjudication', 'lineage_links', 'claim_decomposition', 'kill_search', 'review', 'watch_check', 'citation_map', 'citation_check', 'snowball', 'followup_search', 'statement_check')),
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

-- One check revision of a statement research: the sentence as the person gave it (the question of `scope_revision`),
-- the request that opened it, what it was frozen from (the discovery run and its read cutoff step, or, in a later
-- slice, a snapshot of the attached files), the model and method package it froze, and the person's choices as they
-- stood (`user_signature`). A revision is never rewritten: `currency` marks it `stale` with the reason, and a new check
-- is a new revision. `status` is `open` while a listed work waits for its check, `finished` once none does.
CREATE TABLE statement_checks (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id) ON DELETE CASCADE,
  revision INTEGER NOT NULL,
  request_id TEXT NOT NULL UNIQUE,
  sentence TEXT NOT NULL,
  sentence_sha256 TEXT NOT NULL,
  scope_revision INTEGER NOT NULL,
  discovery_run_id TEXT REFERENCES runs(id),
  cutoff_step_id TEXT REFERENCES run_steps(id),
  attachment_snapshot_json TEXT,
  user_signature TEXT NOT NULL,
  effort TEXT NOT NULL CHECK (effort IN ('quick', 'standard', 'detailed')),
  work_cap INTEGER NOT NULL,
  model_json TEXT NOT NULL,
  skill_package_hash TEXT NOT NULL,
  run_id TEXT REFERENCES runs(id),
  currency TEXT NOT NULL DEFAULT 'current' CHECK (currency IN ('current', 'stale')),
  stale_reason TEXT,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'finished')),
  created_at TEXT NOT NULL,
  UNIQUE (research_id, revision),
  CHECK ((discovery_run_id IS NOT NULL AND cutoff_step_id IS NOT NULL) <> (attachment_snapshot_json IS NOT NULL)),
  CHECK ((currency = 'stale') = (stale_reason IS NOT NULL))
);

-- One work of one check revision, written once at the freeze. `eligibility` says whether it is on the list:
-- `listed`, `out_of_cap` (beyond the revision's work cap), `excluded_reason` (the read cutoff or the record set it
-- aside; the reason is kept) or `person_excluded`. Only a listed work has an execution `status` (`planned`, `done`,
-- `could_not_check`, `no_text`), and only a `done` one a `result`, V3's results (D99). `entry` says why it is on the
-- list: the person included it, or the reading reached it. The frozen plan (`plan_json`) holds the given passage ids
-- and their text hashes, the pool's fingerprint, the selection signature and the counts; `asset_id` and
-- `extraction_version` name the file its pages came from, and `extraction_complete` whether that extraction succeeded
-- in full. The check itself keeps its StepInput, run, model, raw output, the backend's located quotes with the passage
-- kinds they came from, and its validation record.
CREATE TABLE statement_check_items (
  id TEXT PRIMARY KEY,
  check_id TEXT NOT NULL REFERENCES statement_checks(id) ON DELETE CASCADE,
  ordinal INTEGER NOT NULL,
  work_id TEXT NOT NULL,
  source_version_id TEXT,
  text_version TEXT CHECK (text_version IN ('preprint', 'publisher', 'upload')),
  route TEXT CHECK (route IN ('fulltext', 'abstract')),
  entry TEXT NOT NULL CHECK (entry IN ('person_included', 'reading')),
  eligibility TEXT NOT NULL CHECK (eligibility IN ('listed', 'out_of_cap', 'excluded_reason', 'person_excluded')),
  excluded_reason TEXT,
  status TEXT CHECK (status IN ('planned', 'done', 'could_not_check', 'no_text')),
  result TEXT CHECK (result IN ('found_whole', 'found_partial', 'not_found_in_given')),
  depth TEXT CHECK (depth IN ('selected_passages', 'abstract', 'full_text')),
  asset_id TEXT,
  extraction_version TEXT,
  extraction_complete INTEGER CHECK (extraction_complete IN (0, 1)),
  plan_json TEXT,
  run_id TEXT REFERENCES runs(id),
  step_input_id TEXT,
  model_json TEXT,
  output_json TEXT,
  raw_output TEXT,
  located_anchors_json TEXT,
  located_passage_kinds_json TEXT,
  validation_json TEXT,
  error_json TEXT,
  checked_at TEXT,
  UNIQUE (check_id, ordinal),
  UNIQUE (check_id, work_id),
  CHECK ((eligibility = 'listed') = (status IS NOT NULL)),
  CHECK ((eligibility = 'excluded_reason') = (excluded_reason IS NOT NULL)),
  -- A result belongs to `done` only, and `done` always has one (V3's rule).
  CHECK ((status = 'done') = (result IS NOT NULL)),
  CHECK (status IS NULL OR status = 'no_text' OR plan_json IS NOT NULL)
);
