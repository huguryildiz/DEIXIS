"""Upgrade steps that bring an existing library to the schema in schema.sql (D119).

Each step is the work one old migration file did (0002 to 0016; 0001 was the baseline schema): the version it raises a
library to, the name the library records for it in `schema_migrations` (the old file name, kept so libraries made before
D119 read the same), whether it runs with foreign keys off (a table rebuilt by SQLite's 12-step procedure), and its SQL.
`db.migrate` runs each step a library has not recorded, in version order, in its own transaction. A new library is made
from schema.sql and records every version up to its header's, so it runs none of these. A schema change edits
schema.sql, raises its version and adds the step with that number here; a recorded step is never edited.
"""

from __future__ import annotations

from typing import NamedTuple


class Step(NamedTuple):
    name: str
    foreign_keys_off: bool
    sql: str


STEPS: dict[int, Step] = {
    2: Step("0002_citation_check.sql", True, """\
-- Verify Citations, slice V1 (D86). A draft owns one internal research row of the new kind `citation_check`, so the
-- run machinery (runs, step_inputs and model_sessions all need a research_id) serves it later; lists, quick search,
-- Library, home and the research routes leave that kind out. Existing researches are `research`. `runs.kind` gains
-- `citation_check`: SQLite cannot change a CHECK in place, so `runs` is rebuilt as 0015 did (SQLite's 12-step
-- procedure): every row is copied unchanged, the list keeps every earlier run kind, and the three triggers that read
-- `runs` are dropped and recreated around it with the same text, as is its index.
ALTER TABLE researches ADD COLUMN kind TEXT NOT NULL DEFAULT 'research' CHECK (kind IN ('research', 'citation_check'));

CREATE TABLE runs_new (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  scope_revision INTEGER NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('discovery', 'answer', 'answer_review', 'followup_answer', 'table_columns', 'table_fill', 'cell_recheck', 'table_column_recheck', 'screen_more', 'research_title', 'pdf_collection', 'pdf_ocr', 'report', 'fulltext_fetch', 'fulltext_adjudication', 'lineage_links', 'claim_decomposition', 'kill_search', 'review', 'watch_check', 'citation_map', 'citation_check')),
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

-- One draft a person gave for checking. `text` is the body read from it (the reference list cut off); marker and
-- sentence offsets point into it. `bibliography_origin` names where the entries came from: the uploaded file
-- (`bibtex`, `ris`), else the draft's own list (`draft_list`, LaTeX `bibitem`), else `none`. Deleting the internal
-- research deletes the draft and, through the cascades below, everything read from it.
CREATE TABLE citation_drafts (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL UNIQUE REFERENCES researches(id) ON DELETE CASCADE,
  original_filename TEXT,
  format TEXT NOT NULL CHECK (format IN ('text', 'md', 'tex', 'docx')),
  text_sha256 TEXT NOT NULL,
  text TEXT NOT NULL,
  bibliography_origin TEXT NOT NULL CHECK (bibliography_origin IN ('bibtex', 'ris', 'draft_list', 'bibitem', 'none')),
  bibliography_filename TEXT,
  bibliography_errors_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL
);

-- One citation occurrence: a marker with the sentence it sits in. `targets_json` lists what the marker names (keys,
-- numbers, author-year items) as the parser read them; `parse_status` is `recognized`, `unrecognized` (no pair is
-- made) or `ambiguous` (an author-year item that names no single entry).
CREATE TABLE citation_markers (
  id TEXT PRIMARY KEY,
  draft_id TEXT NOT NULL REFERENCES citation_drafts(id) ON DELETE CASCADE,
  ordinal INTEGER NOT NULL,
  sentence TEXT NOT NULL,
  sentence_start INTEGER NOT NULL, sentence_end INTEGER NOT NULL,
  char_start INTEGER NOT NULL, char_end INTEGER NOT NULL,
  raw TEXT NOT NULL,
  style TEXT NOT NULL CHECK (style IN ('latex', 'numeric', 'author_year')),
  parse_status TEXT NOT NULL CHECK (parse_status IN ('recognized', 'unrecognized', 'ambiguous')),
  targets_json TEXT NOT NULL DEFAULT '[]',
  UNIQUE (draft_id, ordinal)
);

-- One bibliography entry as the person gave it. The parsed fields are the entry's own words, used only to find the
-- record; titles, authors and years shown later come from the resolved source version. `resolution_status`:
-- `pending` (not asked yet), `resolved` (one record by DOI, arXiv id or one close title), `unresolved` (asked: none or
-- several), `lookup_failed` (the provider did not answer; asked again on the next resolve). `resolution_origin` is
-- `code` for a lookup and `user` for a person's own link. A purged source version clears the link, never the entry.
CREATE TABLE citation_bib_entries (
  id TEXT PRIMARY KEY,
  draft_id TEXT NOT NULL REFERENCES citation_drafts(id) ON DELETE CASCADE,
  ordinal INTEGER NOT NULL,
  origin TEXT NOT NULL CHECK (origin IN ('bibtex', 'ris', 'draft_list', 'bibitem')),
  entry_key TEXT, entry_number INTEGER,
  raw_entry TEXT NOT NULL,
  doi TEXT, arxiv_id TEXT, title TEXT, authors_json TEXT NOT NULL DEFAULT '[]', year INTEGER, year_suffix TEXT,
  resolution_status TEXT NOT NULL DEFAULT 'pending'
    CHECK (resolution_status IN ('pending', 'resolved', 'unresolved', 'lookup_failed')),
  resolution_method TEXT CHECK (resolution_method IN ('doi', 'arxiv', 'title')),
  resolution_reason TEXT,
  resolved_source_version_id TEXT REFERENCES source_versions(id) ON DELETE SET NULL,
  resolved_openalex_id TEXT,
  resolution_origin TEXT CHECK (resolution_origin IN ('code', 'user')),
  resolved_at TEXT,
  UNIQUE (draft_id, ordinal),
  CHECK ((resolution_status = 'resolved') = (resolution_origin IS NOT NULL))
);

-- One (citation occurrence, entry) pair, in draft order. `target` is the key, number or author-year item of the marker
-- that named the entry; a target with no single entry has none and is `unresolved` or `ambiguous`.
-- `passage_plan_json` is the frozen passage plan (V2).
CREATE TABLE citation_pairs (
  id TEXT PRIMARY KEY,
  draft_id TEXT NOT NULL REFERENCES citation_drafts(id) ON DELETE CASCADE,
  marker_id TEXT NOT NULL REFERENCES citation_markers(id) ON DELETE CASCADE,
  bib_entry_id TEXT REFERENCES citation_bib_entries(id) ON DELETE CASCADE,
  target TEXT NOT NULL,
  ordinal INTEGER NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('planned', 'done', 'could_not_check', 'out_of_cap', 'no_text', 'unresolved',
                                         'unrecognized', 'ambiguous')),
  passage_plan_json TEXT,
  created_at TEXT NOT NULL,
  UNIQUE (marker_id, target),
  UNIQUE (draft_id, ordinal),
  CHECK (bib_entry_id IS NOT NULL OR status IN ('unresolved', 'ambiguous'))
);

-- One check of a pair (V3): the model output, the anchors the backend located, the depth read, and the code's result.
-- A result exists only for `done`.
CREATE TABLE citation_checks (
  id TEXT PRIMARY KEY,
  pair_id TEXT NOT NULL REFERENCES citation_pairs(id) ON DELETE CASCADE,
  step_id TEXT REFERENCES run_steps(id) ON DELETE SET NULL,
  output_json TEXT,
  located_anchors_json TEXT,
  depth TEXT CHECK (depth IN ('selected_passages', 'abstract', 'full_text')),
  result TEXT CHECK (result IN ('found_whole', 'found_partial', 'not_found_in_given')),
  status TEXT NOT NULL CHECK (status IN ('planned', 'done', 'could_not_check', 'out_of_cap', 'no_text', 'unresolved',
                                         'unrecognized', 'ambiguous')),
  error_json TEXT,
  created_at TEXT NOT NULL,
  CHECK ((status = 'done') = (result IS NOT NULL))
);

CREATE INDEX citation_markers_draft ON citation_markers(draft_id, ordinal);
CREATE INDEX citation_bib_entries_draft ON citation_bib_entries(draft_id, ordinal);
CREATE INDEX citation_bib_entries_source ON citation_bib_entries(resolved_source_version_id);
CREATE INDEX citation_pairs_marker ON citation_pairs(marker_id);
CREATE INDEX citation_pairs_entry ON citation_pairs(bib_entry_id);
CREATE INDEX citation_checks_pair ON citation_checks(pair_id);
"""),
    3: Step("0003_snowball.sql", True, """\
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
"""),
    4: Step("0004_followup_search.sql", True, """\
-- Follow-up search (D92). A follow-up that asks for works the research does not hold can start a search of its own,
-- a run of the new kind `followup_search` under the turn's question revision. `runs` is rebuilt as 0002 and 0003 did (SQLite's
-- 12-step procedure): every row is copied unchanged, the list keeps every earlier run kind, and the three triggers
-- that read `runs` are dropped and recreated around it with the same text, as is its index.
CREATE TABLE runs_new (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  scope_revision INTEGER NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('discovery', 'answer', 'answer_review', 'followup_answer', 'table_columns', 'table_fill', 'cell_recheck', 'table_column_recheck', 'screen_more', 'research_title', 'pdf_collection', 'pdf_ocr', 'report', 'fulltext_fetch', 'fulltext_adjudication', 'lineage_links', 'claim_decomposition', 'kill_search', 'review', 'watch_check', 'citation_map', 'citation_check', 'snowball', 'followup_search')),
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
"""),
    5: Step("0005_citation_check_text.sql", False, """\
-- Verify Citations, slice V2 (D96): the text each bibliography entry is read from, the person's own PDF for an entry,
-- and the frozen passage plan's revisions. Columns only; 0002's tables are not rebuilt.
--
-- Per entry: `upload_source_version_id` is the person's PDF attached to that entry (an uploaded source of the draft's
-- internal research) and `upload_identity` what `identity.check` read on its first pages (`doi`, `title` or
-- `unconfirmed`; the last is shown as a flag, never hidden). `text_status` is `pending` until acquisition has decided
-- the entry's text, then `settled`; `available_text` is `full_text`, `abstract` or `metadata_only`; `text_version` is
-- `preprint`, `publisher` or `upload` (null when the record names no version); `text_origin` says where the text came
-- from; `text_note` why an entry has less than full text or is still pending.
ALTER TABLE citation_bib_entries ADD COLUMN upload_source_version_id TEXT REFERENCES source_versions(id) ON DELETE SET NULL;
ALTER TABLE citation_bib_entries ADD COLUMN upload_identity TEXT CHECK (upload_identity IN ('doi', 'title', 'unconfirmed'));
ALTER TABLE citation_bib_entries ADD COLUMN text_status TEXT NOT NULL DEFAULT 'pending' CHECK (text_status IN ('pending', 'settled'));
ALTER TABLE citation_bib_entries ADD COLUMN available_text TEXT CHECK (available_text IN ('full_text', 'abstract', 'metadata_only'));
ALTER TABLE citation_bib_entries ADD COLUMN text_source_version_id TEXT REFERENCES source_versions(id) ON DELETE SET NULL;
ALTER TABLE citation_bib_entries ADD COLUMN text_version TEXT CHECK (text_version IN ('preprint', 'publisher', 'upload'));
ALTER TABLE citation_bib_entries ADD COLUMN text_origin TEXT CHECK (text_origin IN ('person_pdf', 'stored_pdf', 'open_access', 'record'));
ALTER TABLE citation_bib_entries ADD COLUMN text_note TEXT;
ALTER TABLE citation_bib_entries ADD COLUMN text_settled_at TEXT;

-- The draft's plan revision: 0 until the first freeze; the person's re-freeze adds one.
ALTER TABLE citation_drafts ADD COLUMN plan_revision INTEGER NOT NULL DEFAULT 0;
ALTER TABLE citation_drafts ADD COLUMN plan_frozen_at TEXT;

-- The revision a pair's `passage_plan_json` belongs to, and every earlier one it had (status and plan), oldest first,
-- so a re-freeze never overwrites what a preview showed.
ALTER TABLE citation_pairs ADD COLUMN plan_revision INTEGER;
ALTER TABLE citation_pairs ADD COLUMN previous_plans_json TEXT NOT NULL DEFAULT '[]';
"""),
    6: Step("0006_citation_check_identity.sql", False, """\
-- Verify Citations, slice V2 review (D96): what `identity.check` read on the PDF an entry's text comes from, whichever
-- path chose it (the person's PDF, a PDF the record already held, an open-access copy), against the versions of the
-- entry's record's work, with the file and extraction it read. Null when the text is an abstract or nothing. A frozen
-- plan copies this result into its own revision, so a later upload never changes an earlier plan's warning.
ALTER TABLE citation_bib_entries ADD COLUMN text_identity TEXT CHECK (text_identity IN ('doi', 'title', 'unconfirmed'));
ALTER TABLE citation_bib_entries ADD COLUMN text_identity_asset_id TEXT;
ALTER TABLE citation_bib_entries ADD COLUMN text_identity_extraction TEXT;
-- The identity result each pair's frozen revision read (planned and out-of-cap pairs; null for `no_text`).
ALTER TABLE citation_pairs ADD COLUMN plan_identity_json TEXT;
"""),
    7: Step("0007_answer_thread_candidates.sql", True, """\
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
"""),
    8: Step("0008_citation_check_result.sql", False, """\
-- Verify Citations, slice V3 (D99): what one check of a pair read and returned. Columns only; 0002's `citation_checks`
-- is not rebuilt. `plan_revision` is the frozen plan revision the check read and `run_id` the run that sent it;
-- `step_input_id` the stored StepInput of its last attempt; `model_json` the connection, the requested and the resolved
-- model; `raw_output` the model's last answer as it came, kept for a check that could not be completed too;
-- `flags_json` the pair's flags as that revision read them (title mismatch, retraction, identity); `basis_json` the
-- depth read with how many passages were given and not given, and which passage kinds the located quotes came from.
ALTER TABLE citation_checks ADD COLUMN plan_revision INTEGER;
ALTER TABLE citation_checks ADD COLUMN run_id TEXT REFERENCES runs(id) ON DELETE SET NULL;
ALTER TABLE citation_checks ADD COLUMN step_input_id TEXT;
ALTER TABLE citation_checks ADD COLUMN model_json TEXT;
ALTER TABLE citation_checks ADD COLUMN raw_output TEXT;
ALTER TABLE citation_checks ADD COLUMN flags_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE citation_checks ADD COLUMN basis_json TEXT;
-- One check per pair and plan revision: a pair that has one is never sent again for that revision.
CREATE UNIQUE INDEX citation_checks_pair_revision ON citation_checks(pair_id, plan_revision);
"""),
    9: Step("0009_statement_check.sql", True, """\
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
"""),
    10: Step("0010_citation_check_claim.sql", False, """\
-- Verify Citations after the V5 pilot (D105): the claim a check reads, kept beside the sentence as written. `claim` is
-- the sentence (or, for a citation in a LaTeX table, its row as "Header: cell" pairs) with the markers cut out and the
-- LaTeX turned into plain text; the model copies its parts from it and coverage is read on it. `claim_context` is a
-- table row's caption, shown to the model and never part of the claim. `sentence` stays the raw text the screen marks
-- the marker in. A draft read before this migration has no claim; its checks read the sentence as before.
-- `parse_reason` says why a marker the parser read was left unrecognized (`table_layout_not_read`), else null.
ALTER TABLE citation_markers ADD COLUMN claim TEXT;
ALTER TABLE citation_markers ADD COLUMN claim_context TEXT;
ALTER TABLE citation_markers ADD COLUMN parse_reason TEXT;
"""),
    11: Step("0011_statement_support_rule.sql", False, """\
-- Reverse citation search R4b (D108): the rule a statement check revision's results are presented by. A revision stored
-- before this migration reads with rule 1 (a work's class is its result, as it always looked); a new revision stores
-- rule 2 (a result counts as support only with at least one `stated` part, else `support_not_shown`). The stored
-- results, parts and quotes are never rewritten; the class is read from them (`domain.statement.support_class`).
ALTER TABLE statement_checks ADD COLUMN support_rule_version INTEGER NOT NULL DEFAULT 1
  CHECK (support_rule_version IN (1, 2));
"""),
    12: Step("0012_spend_reprice.sql", False, """\
-- Spend ledger repricing (D111): a call booked with no cost because its model was not in the price list gets a cost once
-- a later list names that model. The row keeps when that happened and the date of the list used, so a cost that was not
-- known when the call was made stays told apart from one priced at the time. NULL on every row priced when written.
ALTER TABLE spend_ledger ADD COLUMN repriced_at TEXT;
ALTER TABLE spend_ledger ADD COLUMN repriced_price_list TEXT;
"""),
    13: Step("0013_equation_model_requests.sql", False, """\
-- The answer model reads numbered display equations from page crops (D113). One row per request for one crop, kept like
-- Mathpix's (D40): reserved before sending, then answered, error or unknown (a timeout or lost connection after sending).
-- `model_revision` names connection, model, effort and a fingerprint prefix of the key (never the key), so a refused key
-- stops further requests until the key or the default model changes. `delivery_class` is the adapter's: a row whose call
-- never left (`before_send`) does not count against the budgets. An answer is reused for the same crop, connection,
-- model, effort and prompt version.
CREATE TABLE equation_model_requests (
  id TEXT PRIMARY KEY,
  crop_sha256 TEXT NOT NULL,
  asset_id TEXT NOT NULL,
  file_sha256 TEXT NOT NULL,
  page INTEGER NOT NULL,
  n TEXT NOT NULL,
  attempt INTEGER NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('reserved', 'answered', 'error', 'unknown')),
  connection TEXT NOT NULL,
  requested_model TEXT NOT NULL,
  resolved_model TEXT,
  reasoning_effort TEXT,
  prompt_version TEXT NOT NULL,
  model_revision TEXT NOT NULL,
  latex TEXT,
  http_status INTEGER,
  delivery_class TEXT,
  error_kind TEXT,
  reason TEXT,
  token_usage_json TEXT,
  reserved_at TEXT NOT NULL,
  answered_at TEXT
);

CREATE INDEX equation_model_requests_crop ON equation_model_requests(crop_sha256, status);

CREATE INDEX equation_model_requests_asset ON equation_model_requests(asset_id);

CREATE INDEX equation_model_requests_month ON equation_model_requests(reserved_at);
"""),
    14: Step("0014_elsevier_pdf_route.sql", True, """\
-- Elsevier's article API as a PDF route (D-number in docs/decisions.md): a lookup and its candidates are stored under
-- the provider `elsevier`. Both tables are rebuilt by SQLite's 12-step procedure with every row copied unchanged by column name and the
-- provider list widened by that one name; their indexes are recreated with the same text. No trigger reads them.
CREATE TABLE pdf_discovery_runs_new (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  provider TEXT NOT NULL CHECK (provider IN ('unpaywall', 'openalex', 'crossref', 'core', 'europepmc', 'elsevier', 'web_search')),
  query_text TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'zero_results', 'auth_required', 'rate_limited', 'timeout', 'parse_error', 'failed')),
  result_count INTEGER NOT NULL DEFAULT 0,
  http_status INTEGER,
  error_code TEXT,
  created_at TEXT NOT NULL,
  finished_at TEXT,
  other_title_count INTEGER NOT NULL DEFAULT 0
, retry_after TEXT, attempt_id TEXT);
INSERT INTO pdf_discovery_runs_new (id, research_id, source_version_id, provider, query_text, status, result_count, http_status, error_code, created_at, finished_at, other_title_count, retry_after, attempt_id)
  SELECT id, research_id, source_version_id, provider, query_text, status, result_count, http_status, error_code, created_at, finished_at, other_title_count, retry_after, attempt_id FROM pdf_discovery_runs;
CREATE TABLE pdf_candidates_new (
  id TEXT PRIMARY KEY,
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  discovery_run_id TEXT NOT NULL REFERENCES "pdf_discovery_runs"(id),
  provider TEXT NOT NULL CHECK (provider IN ('unpaywall', 'openalex', 'crossref', 'core', 'europepmc', 'elsevier', 'web_search')),
  candidate_url TEXT NOT NULL,
  landing_url TEXT,
  version_label TEXT,
  license TEXT,
  identity_status TEXT NOT NULL CHECK (identity_status IN ('doi_verified', 'title_verified', 'unverified', 'mismatch')),
  version_status TEXT NOT NULL CHECK (version_status IN ('match', 'different', 'uncertain')),
  access_status TEXT NOT NULL CHECK (access_status IN ('not_attempted', 'downloaded', 'http_error', 'not_pdf', 'too_large', 'timeout', 'blocked_url', 'wrong_type', 'failed')),
  http_status INTEGER,
  error_code TEXT,
  final_url TEXT,
  discovered_at TEXT NOT NULL,
  attempted_at TEXT,
  UNIQUE (source_version_id, provider, candidate_url)
);
INSERT INTO pdf_candidates_new (id, source_version_id, discovery_run_id, provider, candidate_url, landing_url, version_label, license, identity_status, version_status, access_status, http_status, error_code, final_url, discovered_at, attempted_at)
  SELECT id, source_version_id, discovery_run_id, provider, candidate_url, landing_url, version_label, license, identity_status, version_status, access_status, http_status, error_code, final_url, discovered_at, attempted_at FROM pdf_candidates;
DROP TABLE pdf_candidates;
DROP TABLE pdf_discovery_runs;
ALTER TABLE pdf_discovery_runs_new RENAME TO pdf_discovery_runs;
ALTER TABLE pdf_candidates_new RENAME TO pdf_candidates;
CREATE INDEX pdf_discovery_source ON pdf_discovery_runs(source_version_id, created_at);
CREATE UNIQUE INDEX pdf_discovery_attempt ON pdf_discovery_runs(attempt_id) WHERE attempt_id IS NOT NULL;
CREATE INDEX pdf_candidates_source ON pdf_candidates(source_version_id, discovered_at);
"""),
    15: Step("0015_statement_field.sql", False, """\
-- The field a statement research's claim belongs to, as the person typed it (reverse citation search, R5): read by the
-- query model step and put first in the code query's setting block. NULL: none typed; the query model names one.
ALTER TABLE scope_revisions ADD COLUMN statement_field TEXT;
"""),
    16: Step("0016_abstract_rows.sql", False, """\
-- D114: a table made from the research (`evidence_tables.follows_included = 2`) also follows the works read from their
-- abstracts only. The column already takes any integer, so no table changes and nothing is backfilled; this file only
-- records the schema version, so a DEIXIS without D114 refuses this library instead of reading those tables as plain
-- included-source tables (`db.check_schema_known`).
SELECT 1;
"""),
}
