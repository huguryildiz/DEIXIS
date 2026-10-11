-- deixis:foreign-keys-off
-- Follow-up questions (UI parity S22a, F17): a person asks a question inside a research and a `followup_answer` run
-- answers it from this research's stored passages, with no new search. SQLite cannot change a CHECK in place, so
-- `runs` is rebuilt as 0004 and 0006 did (SQLite's 12-step procedure): every row is copied unchanged, the list keeps
-- every run kind of those migrations (`screen_more` included, whether 0006 ran first or not), and the triggers that
-- read `runs` are dropped and recreated around it with the same text.
CREATE TABLE runs_new (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  scope_revision INTEGER NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('discovery', 'answer', 'answer_review', 'followup_answer', 'table_columns', 'table_fill', 'cell_recheck', 'table_column_recheck', 'screen_more', 'research_title', 'pdf_collection', 'pdf_ocr', 'report', 'fulltext_fetch', 'fulltext_adjudication', 'lineage_links', 'claim_decomposition', 'kill_search', 'review', 'watch_check')),
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

-- One follow-up question and, once published, its answer. The row is written `pending` with its run and changes once,
-- in the same transaction as its evidence links, when the answer is published; it is never edited after that, and
-- only the research purge (which authorizes it) deletes it. `scope_revision` is the question revision the turn was
-- asked under. `status`: `answered` / `partly_answered` / `not_answered` are the model's outcome on a valid output;
-- `no_passages` means this research held no passage to give and no model was asked; `unverified_draft` is an output
-- that stayed invalid after its one repair and is never shown as a cited answer. `passages_considered` is how many
-- stored passages of this research the selection ranked, `passages_given` how many it sent (the StepInput's allowlist).
-- No trigger here reads `runs`, so a later rebuild of `runs` has no new trigger to drop and recreate; the code that
-- writes a turn writes its `followup_answer` run in the same transaction.
CREATE TABLE followup_turns (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  scope_revision INTEGER NOT NULL,
  question TEXT NOT NULL CHECK (length(question) BETWEEN 1 AND 2000),
  run_id TEXT NOT NULL UNIQUE REFERENCES runs(id),
  status TEXT NOT NULL CHECK (status IN ('pending', 'answered', 'partly_answered', 'not_answered', 'no_passages', 'unverified_draft')),
  step_id TEXT REFERENCES run_steps(id),
  step_input_id TEXT REFERENCES step_inputs(id),
  answer_language TEXT,
  draft_json TEXT,
  validation_json TEXT,
  passages_considered INTEGER,
  passages_given INTEGER,
  created_at TEXT NOT NULL,
  published_at TEXT,
  CHECK ((status = 'pending') = (published_at IS NULL)),
  CHECK (status IN ('pending', 'no_passages') OR step_input_id IS NOT NULL)
);
CREATE INDEX followup_turns_research ON followup_turns(research_id, created_at);
CREATE TRIGGER followup_turns_publish_once BEFORE UPDATE ON followup_turns
WHEN OLD.status != 'pending' OR NEW.id IS NOT OLD.id OR NEW.research_id IS NOT OLD.research_id
 OR NEW.scope_revision IS NOT OLD.scope_revision OR NEW.question IS NOT OLD.question OR NEW.run_id IS NOT OLD.run_id
 OR NEW.created_at IS NOT OLD.created_at
BEGIN SELECT RAISE(ABORT, 'a follow-up turn is published once and never edited'); END;
CREATE TRIGGER followup_turns_no_delete BEFORE DELETE ON followup_turns
WHEN NOT EXISTS (SELECT 1 FROM research_purge_authorizations WHERE research_id = OLD.research_id)
BEGIN SELECT RAISE(ABORT, 'followup_turns requires research purge authorization'); END;

-- The claim-passage links of a published follow-up answer: passage, source version and StepInput from the stored
-- StepInput, the anchor located by the backend in the stored passage text. Append-only, like the turn.
CREATE TABLE followup_turn_links (
  id TEXT PRIMARY KEY,
  turn_id TEXT NOT NULL REFERENCES followup_turns(id),
  claim_label TEXT NOT NULL,
  passage_id TEXT NOT NULL REFERENCES passages(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  step_input_id TEXT NOT NULL REFERENCES step_inputs(id),
  support_type TEXT NOT NULL CHECK (support_type IN ('source_stated', 'analyst_inference')),
  anchor_text TEXT NOT NULL,
  anchor_match TEXT NOT NULL CHECK (anchor_match IN ('exact', 'normalized', 'fuzzy')),
  UNIQUE (turn_id, claim_label, passage_id)
);
CREATE INDEX followup_turn_links_source ON followup_turn_links(source_version_id);
CREATE TRIGGER followup_turn_links_no_update BEFORE UPDATE ON followup_turn_links
BEGIN SELECT RAISE(ABORT, 'followup_turn_links is append-only'); END;
CREATE TRIGGER followup_turn_links_no_delete BEFORE DELETE ON followup_turn_links
WHEN NOT EXISTS (SELECT 1 FROM research_purge_authorizations r JOIN followup_turns t ON t.research_id = r.research_id
                 WHERE t.id = OLD.turn_id)
BEGIN SELECT RAISE(ABORT, 'followup_turn_links requires research purge authorization'); END;
CREATE TRIGGER followup_turn_links_insert_guard BEFORE INSERT ON followup_turn_links
WHEN NOT EXISTS (SELECT 1 FROM followup_turns t WHERE t.id = NEW.turn_id AND t.step_input_id = NEW.step_input_id
                 AND t.status IN ('answered', 'partly_answered', 'not_answered'))
BEGIN SELECT RAISE(ABORT, 'a follow-up link belongs to a published valid answer of the same StepInput'); END;
