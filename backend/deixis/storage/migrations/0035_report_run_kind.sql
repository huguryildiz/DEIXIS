-- deixis:foreign-keys-off
-- The `report` run kind writes a section-by-section research report from the evidence table snapshot (P6 slice 1).
-- SQLite cannot widen a CHECK in place, so runs is rebuilt as in 0028/0032; migrate() checks foreign keys after commit.
CREATE TABLE runs_new (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  scope_revision INTEGER NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('discovery', 'answer', 'table_columns', 'table_fill', 'cell_recheck', 'research_title', 'pdf_collection', 'pdf_ocr', 'report')),
  status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'pause_requested', 'paused', 'completed', 'failed', 'cancelled')),
  stage TEXT NOT NULL CHECK (stage IN ('intake', 'discovery', 'screening', 'inspection', 'answer', 'extraction', 'synthesis', 'candidate', 'claim_check', 'export')),
  pause_reason TEXT,
  error_json TEXT,
  budget_json TEXT NOT NULL,
  usage_json TEXT NOT NULL DEFAULT '{}',
  idempotency_key TEXT UNIQUE,
  -- Table runs: {"table_id", "column_ids", "cell_id", "include_stale"}. Report runs: {"report_id"}. NULL otherwise.
  target_json TEXT,
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
INSERT INTO runs_new (id, research_id, scope_revision, kind, status, stage, pause_reason, error_json, budget_json,
                      usage_json, idempotency_key, target_json, version, created_at, updated_at)
  SELECT id, research_id, scope_revision, kind, status, stage, pause_reason, error_json, budget_json,
         usage_json, idempotency_key, target_json, version, created_at, updated_at FROM runs;
DROP TABLE runs;
ALTER TABLE runs_new RENAME TO runs;
CREATE INDEX runs_status ON runs(status, created_at);

-- One report belongs to one research and one run kind='report'. report_version is assigned only when status
-- becomes 'valid' (parallel to answers.report_version, migration 0023); a 'draft' report has no report_version.
CREATE TABLE reports (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  run_id TEXT NOT NULL REFERENCES runs(id),
  scope_revision INTEGER NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('in_progress', 'valid', 'draft')),
  language TEXT,
  plan_json TEXT,
  report_version INTEGER,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX reports_report_version ON reports (research_id, report_version) WHERE report_version IS NOT NULL;
CREATE INDEX reports_research ON reports (research_id, created_at);

-- One row per section of one report. status mirrors the section state machine (see "Durum makineleri").
CREATE TABLE report_sections (
  id TEXT PRIMARY KEY,
  report_id TEXT NOT NULL REFERENCES reports(id),
  section_id TEXT NOT NULL CHECK (section_id IN ('I', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'abstract', 'index_terms')),
  step_id TEXT REFERENCES run_steps(id),
  status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'valid', 'draft', 'failed')),
  draft_json TEXT,
  validation_json TEXT,
  word_count INTEGER,
  ordinal INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (report_id, section_id)
);

-- One claim of one section, same shape as `claims` (migration 0007-era) with section_id carried by the parent row
-- instead of a free-text column, and the report-only fields (§4 "Bölüm şeması").
CREATE TABLE report_claims (
  id TEXT PRIMARY KEY,
  report_section_id TEXT NOT NULL REFERENCES report_sections(id),
  claim_key TEXT NOT NULL,
  ordinal INTEGER NOT NULL,
  paragraph INTEGER NOT NULL,
  text TEXT NOT NULL,
  support_type TEXT NOT NULL CHECK (support_type IN ('source_stated', 'analyst_inference')),
  table_ref TEXT,
  equation_ref TEXT,
  axis_id TEXT,
  count_json TEXT,
  equation_origin_json TEXT,
  UNIQUE (report_section_id, claim_key)
);

-- body_refs (abstract/I/IX -> body claim_key) and gap_refs (VI/VII -> gap_id) as rows, not JSON arrays, so assembly
-- checks (§8) can query them with SQL the same way evidence_links joins claims today.
CREATE TABLE report_claim_refs (
  claim_id TEXT NOT NULL REFERENCES report_claims(id),
  ref_kind TEXT NOT NULL CHECK (ref_kind IN ('body_ref', 'gap_ref')),
  ref_value TEXT NOT NULL
);
CREATE INDEX report_claim_refs_claim ON report_claim_refs (claim_id);

-- Same shape as evidence_links (migration 0007-era), except exactly one of passage_id/cell_id is set: a claim can
-- cite a table cell's stored evidence quote as well as, or instead of, a passage directly.
CREATE TABLE report_citation_links (
  id TEXT PRIMARY KEY,
  claim_id TEXT NOT NULL REFERENCES report_claims(id),
  passage_id TEXT REFERENCES passages(id),
  cell_id TEXT REFERENCES evidence_cells(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  step_input_id TEXT NOT NULL REFERENCES step_inputs(id),
  anchor_text TEXT,
  anchor_match TEXT CHECK (anchor_match IN ('exact', 'normalized', 'fuzzy')),
  CHECK ((passage_id IS NOT NULL) <> (cell_id IS NOT NULL))
);
CREATE INDEX report_citation_links_claim ON report_citation_links (claim_id);

-- kind is plain TEXT, checked in code against domain.contracts.GAP_KINDS, not a SQL CHECK: slice 2 (Chain of
-- Ideas) adds a fourth kind and must not require a migration to do it.
CREATE TABLE report_gaps (
  id TEXT PRIMARY KEY,
  report_id TEXT NOT NULL REFERENCES reports(id),
  gap_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  text TEXT NOT NULL,
  basis_json TEXT NOT NULL,
  provenance_json TEXT NOT NULL,
  kill_search_status TEXT NOT NULL DEFAULT 'not_run' CHECK (kill_search_status IN ('not_run', 'narrowed', 'closed', 'open')),
  created_at TEXT NOT NULL,
  UNIQUE (report_id, gap_id)
);

-- §4.2's frozen evidence snapshot. snapshot_json holds the table/column/cell revisions, included source version ids
-- and reading depths, and corpus counts as they stood when the report run started.
CREATE TABLE report_snapshot (
  report_id TEXT PRIMARY KEY REFERENCES reports(id),
  table_id TEXT NOT NULL REFERENCES evidence_tables(id),
  table_revision INTEGER NOT NULL,
  snapshot_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

-- One row per attempted targeted phrase repair (§8). outcome distinguishes a kept rewrite from the two exception
-- kinds decision 12 introduced: a review-reverted rewrite, and a rewrite that still fails the frame check.
CREATE TABLE report_phrase_repairs (
  id TEXT PRIMARY KEY,
  report_id TEXT NOT NULL REFERENCES reports(id),
  section_id TEXT NOT NULL,
  sentence_id TEXT NOT NULL,
  before TEXT NOT NULL,
  after TEXT NOT NULL,
  outcome TEXT NOT NULL CHECK (outcome IN ('kept', 'reverted_exception', 'unframed_exception')),
  created_at TEXT NOT NULL
);
CREATE INDEX report_phrase_repairs_report ON report_phrase_repairs (report_id);
