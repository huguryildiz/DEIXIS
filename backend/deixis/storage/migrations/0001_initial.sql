-- DEIXIS first migration: only the records P1–P4 need.
-- Identifiers are allocated by DEIXIS; provider IDs and DOIs are mappings, never primary keys.

CREATE TABLE researches (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  current_scope_revision INTEGER NOT NULL DEFAULT 1,
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE scope_revisions (
  research_id TEXT NOT NULL REFERENCES researches(id),
  revision INTEGER NOT NULL,
  question TEXT NOT NULL,
  language_hint TEXT,
  source_scope TEXT NOT NULL CHECK (source_scope IN ('academic', 'attached', 'attached_and_academic')),
  providers_json TEXT NOT NULL,
  effort TEXT NOT NULL CHECK (effort IN ('quick', 'standard', 'detailed')),
  model_connection TEXT NOT NULL,
  requested_model TEXT,
  steering TEXT,
  created_at TEXT NOT NULL,
  PRIMARY KEY (research_id, revision)
);

CREATE TABLE runs (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  scope_revision INTEGER NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('discovery', 'answer')),
  status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'pause_requested', 'paused', 'completed', 'failed', 'cancelled')),
  stage TEXT NOT NULL CHECK (stage IN ('intake', 'discovery', 'screening', 'inspection', 'answer', 'synthesis', 'candidate', 'claim_check', 'export')),
  pause_reason TEXT,
  error_json TEXT,
  budget_json TEXT NOT NULL,
  usage_json TEXT NOT NULL DEFAULT '{}',
  idempotency_key TEXT UNIQUE,
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX runs_status ON runs(status, created_at);

CREATE TABLE run_steps (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES runs(id),
  operation_key TEXT NOT NULL,
  kind TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'succeeded', 'partial', 'failed', 'cancelled', 'outcome_unknown')),
  attempt INTEGER NOT NULL DEFAULT 0,
  delivery_class TEXT CHECK (delivery_class IS NULL OR delivery_class IN ('before_send', 'rejected_not_executed', 'after_send_unknown')),
  error_code TEXT,
  error_json TEXT,
  output_json TEXT,
  started_at TEXT,
  finished_at TEXT,
  UNIQUE (run_id, operation_key)
);

CREATE TABLE step_inputs (
  id TEXT PRIMARY KEY,
  step_id TEXT NOT NULL REFERENCES run_steps(id),
  research_id TEXT NOT NULL REFERENCES researches(id),
  run_id TEXT NOT NULL REFERENCES runs(id),
  attempt INTEGER NOT NULL,
  task_type TEXT NOT NULL,
  scope_revision INTEGER NOT NULL,
  skill_package_hash TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  base_instructions TEXT NOT NULL,
  developer_instructions TEXT NOT NULL,
  user_message TEXT NOT NULL,
  output_schema_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TRIGGER step_inputs_no_update BEFORE UPDATE ON step_inputs
BEGIN SELECT RAISE(ABORT, 'step_inputs are immutable'); END;
CREATE TRIGGER step_inputs_no_delete BEFORE DELETE ON step_inputs
BEGIN SELECT RAISE(ABORT, 'step_inputs are immutable'); END;

CREATE TABLE model_sessions (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  run_id TEXT NOT NULL REFERENCES runs(id),
  step_id TEXT NOT NULL REFERENCES run_steps(id),
  step_input_id TEXT NOT NULL REFERENCES step_inputs(id),
  connection TEXT NOT NULL,
  requested_model TEXT,
  resolved_model TEXT,
  external_thread_id TEXT,
  status TEXT NOT NULL,
  raw_output TEXT,
  validation_json TEXT,
  token_usage_json TEXT,
  tool_item_types_json TEXT,
  started_at TEXT NOT NULL,
  finished_at TEXT
);

CREATE TABLE events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  research_id TEXT NOT NULL REFERENCES researches(id),
  run_id TEXT,
  type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX events_research ON events(research_id, id);

CREATE TABLE worker_owner (
  singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
  instance_id TEXT NOT NULL,
  pid INTEGER NOT NULL,
  process_started_at TEXT NOT NULL,
  heartbeat_at TEXT NOT NULL
);

CREATE TABLE works (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL
);

CREATE TABLE source_versions (
  id TEXT PRIMARY KEY,
  work_id TEXT NOT NULL REFERENCES works(id),
  title TEXT NOT NULL,
  authors_json TEXT NOT NULL DEFAULT '[]',
  year INTEGER,
  venue TEXT,
  version_label TEXT,
  publication_type TEXT,
  doi TEXT,
  landing_url TEXT,
  oa_pdf_url TEXT,
  origin TEXT NOT NULL CHECK (origin IN ('provider', 'user_upload')),
  provider_payload_path TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE identifier_mappings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  scheme TEXT NOT NULL,
  value TEXT NOT NULL,
  provider TEXT NOT NULL,
  retrieved_at TEXT NOT NULL,
  UNIQUE (scheme, value, source_version_id)
);
CREATE INDEX identifier_lookup ON identifier_mappings(scheme, value);

CREATE TABLE source_assets (
  id TEXT PRIMARY KEY,
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  sha256 TEXT NOT NULL,
  byte_size INTEGER NOT NULL,
  media_type TEXT NOT NULL,
  storage_path TEXT NOT NULL,
  original_filename TEXT,
  retrieved_from TEXT,
  retrieved_at TEXT NOT NULL,
  origin TEXT NOT NULL CHECK (origin IN ('download', 'user_upload')),
  extraction_status TEXT NOT NULL CHECK (extraction_status IN ('pending', 'succeeded', 'partial', 'no_text', 'failed')),
  extraction_version TEXT,
  extraction_error TEXT,
  page_count INTEGER
);

CREATE TABLE passages (
  id TEXT PRIMARY KEY,
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  asset_id TEXT REFERENCES source_assets(id),
  kind TEXT NOT NULL CHECK (kind IN ('abstract', 'pdf_page', 'section')),
  physical_page INTEGER,
  printed_label TEXT,
  abstract_origin TEXT,
  payload_ref TEXT,
  extraction_version TEXT,
  text TEXT NOT NULL,
  text_sha256 TEXT NOT NULL,
  retrieved_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  CHECK (kind <> 'abstract' OR (physical_page IS NULL AND abstract_origin IS NOT NULL)),
  CHECK (kind <> 'pdf_page' OR (physical_page IS NOT NULL AND asset_id IS NOT NULL))
);
CREATE INDEX passages_source ON passages(source_version_id);

CREATE VIRTUAL TABLE passages_fts USING fts5(text, content='passages', content_rowid='rowid');
CREATE TRIGGER passages_fts_insert AFTER INSERT ON passages
BEGIN INSERT INTO passages_fts(rowid, text) VALUES (new.rowid, new.text); END;
CREATE TRIGGER passages_no_update BEFORE UPDATE OF text, source_version_id, kind, physical_page ON passages
BEGIN SELECT RAISE(ABORT, 'passage content is immutable; create a new passage'); END;

CREATE TABLE search_runs (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  run_id TEXT NOT NULL REFERENCES runs(id),
  step_id TEXT NOT NULL REFERENCES run_steps(id),
  provider TEXT NOT NULL,
  query_text TEXT NOT NULL,
  request_description TEXT NOT NULL,
  access_mode TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('completed', 'zero_results', 'auth_required', 'entitlement_missing', 'rate_limited', 'timeout', 'parse_error', 'partial', 'failed')),
  delivery_class TEXT,
  result_count INTEGER NOT NULL DEFAULT 0,
  provider_total INTEGER,
  page_limit INTEGER NOT NULL,
  error_json TEXT,
  raw_payload_path TEXT,
  retrieved_at TEXT NOT NULL
);

CREATE TABLE candidates (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  search_run_id TEXT REFERENCES search_runs(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  rank INTEGER,
  created_at TEXT NOT NULL,
  UNIQUE (research_id, source_version_id)
);

CREATE TABLE corpus_memberships (
  research_id TEXT NOT NULL REFERENCES researches(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  added_by TEXT NOT NULL CHECK (added_by IN ('search', 'user_upload')),
  created_at TEXT NOT NULL,
  PRIMARY KEY (research_id, source_version_id)
);

CREATE TABLE selections (
  research_id TEXT NOT NULL REFERENCES researches(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  state TEXT NOT NULL CHECK (state IN ('included', 'excluded', 'pending')),
  origin TEXT NOT NULL CHECK (origin IN ('default', 'model_proposal', 'user')),
  user_reason TEXT,
  proposal TEXT CHECK (proposal IS NULL OR proposal IN ('include', 'exclude', 'uncertain')),
  proposal_reason TEXT,
  proposal_basis TEXT,
  proposal_step_id TEXT REFERENCES run_steps(id),
  version INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (research_id, source_version_id)
);

CREATE TABLE selection_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  research_id TEXT NOT NULL,
  source_version_id TEXT NOT NULL,
  old_state TEXT,
  new_state TEXT NOT NULL,
  origin TEXT NOT NULL,
  reason TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE answers (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  run_id TEXT NOT NULL REFERENCES runs(id),
  step_id TEXT REFERENCES run_steps(id),
  step_input_id TEXT REFERENCES step_inputs(id),
  scope_revision INTEGER NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('structurally_valid', 'unverified_draft', 'clarification', 'no_evidence')),
  answer_language TEXT,
  draft_json TEXT,
  validation_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE claims (
  id TEXT PRIMARY KEY,
  answer_id TEXT NOT NULL REFERENCES answers(id),
  label TEXT NOT NULL,
  ordinal INTEGER NOT NULL,
  text TEXT NOT NULL,
  support_type TEXT NOT NULL CHECK (support_type IN ('source_stated', 'analyst_inference')),
  semantic_review TEXT NOT NULL DEFAULT 'not_checked' CHECK (semantic_review IN ('not_checked', 'model_assessed', 'human_checked')),
  UNIQUE (answer_id, label)
);

CREATE TABLE evidence_links (
  id TEXT PRIMARY KEY,
  claim_id TEXT NOT NULL REFERENCES claims(id),
  passage_id TEXT NOT NULL REFERENCES passages(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  step_input_id TEXT NOT NULL REFERENCES step_inputs(id),
  UNIQUE (claim_id, passage_id)
);
