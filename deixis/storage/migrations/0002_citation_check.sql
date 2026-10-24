-- deixis:foreign-keys-off
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
