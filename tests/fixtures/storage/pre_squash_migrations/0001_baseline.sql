-- Clean-start baseline of 2026-10-10 (D261): the whole schema in one file. It squashes the old
-- 0001-0077 migration chain, which stays in git history.

CREATE TABLE researches (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  current_scope_revision INTEGER NOT NULL DEFAULT 1,
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
, selection_revision INTEGER NOT NULL DEFAULT 0, trashed_at TEXT);

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
  created_at TEXT NOT NULL, reasoning_effort TEXT, literature_model TEXT, literature_reasoning_effort TEXT, review_mode TEXT NOT NULL DEFAULT 'default' CHECK (review_mode IN ('default', 'custom', 'off')), review_model TEXT, review_reasoning_effort TEXT, literature_connection TEXT, review_connection TEXT, seed_mode TEXT NOT NULL DEFAULT 'question_only'
  CHECK (seed_mode IN ('question_only', 'uploaded_seed')), seed_snapshot_json TEXT, search_workflow TEXT NOT NULL DEFAULT 'sw' CHECK (search_workflow = 'sw'), key_terms TEXT,
  PRIMARY KEY (research_id, revision)
);

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
  finished_at TEXT, protocol_hash TEXT,
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
, selection_revision INTEGER, payload_sha256 TEXT);

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
, output_sha256 TEXT);

CREATE TABLE events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  research_id TEXT NOT NULL REFERENCES researches(id),
  run_id TEXT,
  type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

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
, source_key TEXT, source_key_basis TEXT CHECK (source_key_basis IN ('author', 'title')));

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
, oa_pdf_version TEXT, cited_by_count INTEGER, cited_by_count_at TEXT, volume TEXT, issue TEXT, pages TEXT, author_keywords_json TEXT, reference_count INTEGER, references_read INTEGER NOT NULL DEFAULT 0);

CREATE TABLE identifier_mappings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  scheme TEXT NOT NULL,
  value TEXT NOT NULL,
  provider TEXT NOT NULL,
  retrieved_at TEXT NOT NULL,
  UNIQUE (scheme, value, source_version_id)
);

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
, removed_at TEXT, removal_reason TEXT CHECK (removal_reason IN ('wrong_file', 'replaced')), replaced_by_asset_id TEXT REFERENCES source_assets(id), identity_confirmed_at TEXT);

CREATE VIRTUAL TABLE passages_fts USING fts5(text, content='passages', content_rowid='rowid');

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
, scope_revision INTEGER, payload_sha256 TEXT, page_number INTEGER, read_limit INTEGER, read_total INTEGER, stop_reason TEXT, unread_count INTEGER, connector_json TEXT);

CREATE TABLE candidates (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  search_run_id TEXT REFERENCES search_runs(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  rank INTEGER,
  created_at TEXT NOT NULL, scope_revision INTEGER,
  UNIQUE (research_id, source_version_id)
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
, selection_revision INTEGER, report_version INTEGER);

CREATE TABLE claims (
  id TEXT PRIMARY KEY,
  answer_id TEXT NOT NULL REFERENCES answers(id),
  label TEXT NOT NULL,
  ordinal INTEGER NOT NULL,
  text TEXT NOT NULL,
  support_type TEXT NOT NULL CHECK (support_type IN ('source_stated', 'analyst_inference')),
  semantic_review TEXT NOT NULL DEFAULT 'not_checked' CHECK (semantic_review IN ('not_checked', 'model_assessed', 'human_checked')), section TEXT,
  UNIQUE (answer_id, label)
);

CREATE TABLE evidence_links (
  id TEXT PRIMARY KEY,
  claim_id TEXT NOT NULL REFERENCES claims(id),
  passage_id TEXT NOT NULL REFERENCES passages(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  step_input_id TEXT NOT NULL REFERENCES step_inputs(id), anchor_text TEXT, anchor_match TEXT CHECK (anchor_match IN ('exact', 'normalized', 'fuzzy')),
  UNIQUE (claim_id, passage_id)
);

CREATE TABLE suspected_duplicates (
  research_id TEXT NOT NULL REFERENCES researches(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  other_source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  basis TEXT NOT NULL CHECK (basis IN ('same_title', 'published_doi')),
  created_at TEXT NOT NULL,
  PRIMARY KEY (research_id, source_version_id, other_source_version_id)
);

CREATE TABLE app_settings (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE answer_reviews (
  id TEXT PRIMARY KEY,
  answer_id TEXT NOT NULL UNIQUE REFERENCES answers(id),
  research_id TEXT NOT NULL REFERENCES researches(id),
  run_id TEXT NOT NULL REFERENCES runs(id),
  step_id TEXT REFERENCES run_steps(id),
  step_input_id TEXT REFERENCES step_inputs(id),
  status TEXT NOT NULL CHECK (status IN ('completed', 'failed')),
  failure_reason TEXT,
  review_json TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE research_purge_authorizations (research_id TEXT PRIMARY KEY);

CREATE TABLE passage_embeddings (
  passage_id TEXT NOT NULL REFERENCES passages(id),
  model TEXT NOT NULL,
  dimensions INTEGER NOT NULL,
  vector BLOB NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (passage_id, model)
);

CREATE TABLE source_similarities (
  research_id TEXT NOT NULL REFERENCES researches(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  scope_revision INTEGER NOT NULL,
  model TEXT NOT NULL,
  similarity REAL NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (research_id, source_version_id, scope_revision, model)
);

CREATE TABLE table_templates (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  columns_json TEXT NOT NULL,  -- [{name, instruction, answer_format, options, allow_multiple, unit_hint}]
  idempotency_key TEXT UNIQUE,
  created_at TEXT NOT NULL,
  trashed_at TEXT
);

CREATE TABLE evidence_tables (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  title TEXT NOT NULL,
  template_id TEXT REFERENCES table_templates(id),
  version INTEGER NOT NULL DEFAULT 1,
  idempotency_key TEXT UNIQUE,
  trashed_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE table_rows (
  table_id TEXT NOT NULL REFERENCES evidence_tables(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  added_by TEXT NOT NULL CHECK (added_by IN ('included_at_creation', 'user')),
  created_at TEXT NOT NULL,
  removed_at TEXT,
  PRIMARY KEY (table_id, source_version_id)
);

CREATE TABLE table_columns (
  id TEXT PRIMARY KEY,
  table_id TEXT NOT NULL REFERENCES evidence_tables(id),
  position INTEGER NOT NULL,
  current_revision INTEGER NOT NULL DEFAULT 1,
  origin TEXT NOT NULL CHECK (origin IN ('user', 'model_suggestion', 'template')),
  suggestion_step_id TEXT REFERENCES run_steps(id),
  version INTEGER NOT NULL DEFAULT 1,
  removed_at TEXT,
  created_at TEXT NOT NULL
, lineage_role TEXT
  CHECK (lineage_role IN ('problem', 'change', 'uncertainty')), accepted_by TEXT CHECK (accepted_by IS NULL OR accepted_by = 'automatic'));

CREATE TABLE column_revisions (
  column_id TEXT NOT NULL REFERENCES table_columns(id),
  revision INTEGER NOT NULL,
  name TEXT NOT NULL,
  instruction TEXT NOT NULL,  -- written as for a human annotator
  answer_format TEXT NOT NULL CHECK (answer_format IN ('choice', 'number_unit', 'yes_no', 'text')),
  options_json TEXT,          -- choice: [{"id": "o1", "label": "..."}]
  allow_multiple INTEGER NOT NULL DEFAULT 0,
  unit_hint TEXT,             -- number_unit: the unit the user expects; nothing is converted
  idempotency_key TEXT UNIQUE,
  created_at TEXT NOT NULL,
  PRIMARY KEY (column_id, revision),
  CHECK ((answer_format = 'choice') = (options_json IS NOT NULL)),
  CHECK (answer_format = 'choice' OR allow_multiple = 0),
  CHECK (answer_format = 'number_unit' OR unit_hint IS NULL)
);

CREATE TABLE evidence_cells (
  id TEXT PRIMARY KEY,
  table_id TEXT NOT NULL REFERENCES evidence_tables(id),
  column_id TEXT NOT NULL REFERENCES table_columns(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  current_revision_id TEXT REFERENCES cell_revisions(id),
  version INTEGER NOT NULL DEFAULT 0,  -- bumped by every human write and whenever the current revision changes
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (column_id, source_version_id)
);

CREATE TABLE cell_revisions (
  id TEXT PRIMARY KEY,
  cell_id TEXT NOT NULL REFERENCES evidence_cells(id),
  kind TEXT NOT NULL CHECK (kind IN ('model_fill', 'model_proposal', 'system_fill', 'human_edit', 'accept_proposal', 'dismiss_proposal')),
  author TEXT NOT NULL CHECK (author IN ('model', 'human', 'system')),
  based_on_revision_id TEXT REFERENCES cell_revisions(id),
  column_revision INTEGER NOT NULL,
  state TEXT CHECK (state IN ('value', 'unknown', 'not_reported', 'not_verified', 'not_applicable', 'inaccessible', 'not_found_in_inspected_scope')),
  value_json TEXT,
  note TEXT,
  reading_depth TEXT CHECK (reading_depth IN ('metadata', 'abstract', 'selected_sections', 'full_text')),
  output_status TEXT CHECK (output_status IN ('structurally_valid', 'unverified_draft')),
  cell_version_at_request INTEGER,
  scope_revision INTEGER,
  run_id TEXT REFERENCES runs(id),
  step_id TEXT REFERENCES run_steps(id),
  step_input_id TEXT REFERENCES step_inputs(id),
  model_connection TEXT,
  resolved_model TEXT,
  idempotency_key TEXT UNIQUE,
  created_at TEXT NOT NULL,
  CHECK ((kind IN ('model_fill', 'model_proposal')) = (author = 'model')),
  CHECK (author <> 'model' OR (step_input_id IS NOT NULL AND output_status IS NOT NULL)),
  CHECK ((kind = 'system_fill') = (author = 'system')),
  CHECK (kind <> 'system_fill' OR state = 'inaccessible'),
  CHECK ((kind IN ('accept_proposal', 'dismiss_proposal')) <= (based_on_revision_id IS NOT NULL)),
  CHECK ((kind = 'dismiss_proposal') = (state IS NULL)),
  CHECK (state IS NULL OR (state IN ('value', 'not_verified')) = (value_json IS NOT NULL))
);

CREATE TABLE "corpus_memberships" (
  research_id TEXT NOT NULL REFERENCES researches(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  added_by TEXT NOT NULL CHECK (added_by IN ('search', 'user_upload', 'zotero_import', 'library')),
  created_at TEXT NOT NULL, removed_at TEXT, removal_note TEXT, found_again_at TEXT,
  PRIMARY KEY (research_id, source_version_id)
);

CREATE TABLE "cell_evidence_links" (
  cell_revision_id TEXT NOT NULL REFERENCES cell_revisions(id),
  passage_id TEXT NOT NULL REFERENCES passages(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  step_input_id TEXT REFERENCES step_inputs(id),  -- the StepInput that gave the passage; kept when a proposal is accepted
  anchor_text TEXT,
  anchor_match TEXT CHECK (anchor_match IN ('exact', 'normalized', 'fuzzy'))
);

CREATE TABLE asset_extractions (
  id TEXT PRIMARY KEY,
  asset_id TEXT NOT NULL REFERENCES source_assets(id),
  extraction_version TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('pending', 'succeeded', 'partial', 'no_text', 'failed')),
  error TEXT,
  page_count INTEGER,
  text_pages INTEGER NOT NULL,
  passage_count INTEGER NOT NULL,
  outcome TEXT NOT NULL CHECK (outcome IN ('current', 'superseded', 'rejected')),
  rejection_reason TEXT,
  created_at TEXT NOT NULL, math_json TEXT, ocr_json TEXT, extractor_profile TEXT NOT NULL DEFAULT 'unknown', recovery_operation_id TEXT REFERENCES asset_recovery_operations(id), baseline_extraction_id TEXT REFERENCES asset_extractions(id), input_observation_id TEXT REFERENCES asset_file_observations(id), diagnostic_only INTEGER NOT NULL DEFAULT 0 CHECK (diagnostic_only IN (0, 1)), decision_code TEXT CHECK (decision_code IS NULL OR decision_code IN ('no_change', 'recovered_text', 'password_diagnosed', 'no_text_diagnosed', 'text_updated', 'recovered_from_corrupt_input', 'candidate_failed', 'augmented_text_would_be_lost', 'status_worse', 'page_count_changed', 'legacy_page_count_untrusted', 'text_page_lost', 'upgraded', 'fewer_text_pages', 'ocr_found_no_text', 'input_not_verified')),
  UNIQUE (asset_id, extraction_version)
);

CREATE TABLE table_purge_authorizations (table_id TEXT PRIMARY KEY);

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
, review_json TEXT);

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
  equation_origin_json TEXT, current_revision_id TEXT REFERENCES report_claim_revisions(id), version INTEGER NOT NULL DEFAULT 1,
  UNIQUE (report_section_id, claim_key)
);

CREATE TABLE report_claim_refs (
  claim_id TEXT NOT NULL REFERENCES report_claims(id),
  ref_kind TEXT NOT NULL CHECK (ref_kind IN ('body_ref', 'gap_ref')),
  ref_value TEXT NOT NULL
);

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

CREATE TABLE report_snapshot (
  report_id TEXT PRIMARY KEY REFERENCES reports(id),
  table_id TEXT NOT NULL REFERENCES evidence_tables(id),
  table_revision INTEGER NOT NULL,
  snapshot_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

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

CREATE TABLE "report_sections" (
  id TEXT PRIMARY KEY,
  report_id TEXT NOT NULL REFERENCES reports(id),
  section_id TEXT NOT NULL CHECK (section_id IN ('I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'abstract', 'index_terms')),
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

CREATE TABLE protocol_records (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  scope_revision INTEGER NOT NULL,
  protocol_revision INTEGER NOT NULL,
  reason TEXT,
  body_json TEXT NOT NULL,
  body_sha256 TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (research_id, protocol_revision)
);

CREATE TABLE stage_decisions (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  stage TEXT NOT NULL CHECK (stage IN ('abstract', 'fulltext')),
  outcome TEXT NOT NULL CHECK (outcome IN ('candidate', 'out_of_scope', 'include', 'criterion_not_met', 'unresolved')),
  reason_code TEXT NOT NULL,
  decided_by TEXT NOT NULL CHECK (decided_by IN ('code', 'model_agreement', 'human')),
  next_step TEXT NOT NULL,
  note TEXT,
  scope_revision INTEGER NOT NULL,
  protocol_hash TEXT,
  criterion_hash TEXT,
  step_id TEXT REFERENCES run_steps(id),
  superseded_at TEXT,
  created_at TEXT NOT NULL,
  CHECK ((stage = 'abstract' AND outcome IN ('candidate', 'out_of_scope', 'unresolved'))
      OR (stage = 'fulltext' AND outcome IN ('include', 'criterion_not_met', 'unresolved')))
);

CREATE TABLE model_proposals (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  stage TEXT NOT NULL CHECK (stage IN ('abstract', 'fulltext')),
  step_id TEXT NOT NULL REFERENCES run_steps(id),
  run_no INTEGER NOT NULL CHECK (run_no IN (1, 2)),
  criterion_part TEXT NOT NULL DEFAULT '',
  label TEXT NOT NULL,
  quote TEXT,
  quote_verified INTEGER CHECK (quote_verified IS NULL OR quote_verified IN (0, 1)),
  quote_passage_id TEXT REFERENCES passages(id),
  quote_page INTEGER,
  created_at TEXT NOT NULL,
  UNIQUE (step_id, source_version_id, criterion_part)
);

CREATE TABLE record_signal_ranks (
  ranking_step_id TEXT NOT NULL REFERENCES run_steps(id),
  research_id TEXT NOT NULL REFERENCES researches(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  signal TEXT NOT NULL,
  rank REAL NOT NULL,
  available INTEGER NOT NULL CHECK (available IN (0, 1)),
  PRIMARY KEY (ranking_step_id, source_version_id, signal)
);

CREATE TABLE "selections" (
  research_id TEXT NOT NULL REFERENCES researches(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  state TEXT NOT NULL CHECK (state IN ('included', 'excluded', 'pending')),
  origin TEXT NOT NULL CHECK (origin IN ('default', 'model_proposal', 'code_rule', 'user')),
  user_reason TEXT,
  proposal TEXT CHECK (proposal IS NULL OR proposal IN ('include', 'exclude', 'uncertain')),
  proposal_reason TEXT,
  proposal_basis TEXT,
  proposal_step_id TEXT REFERENCES run_steps(id),
  version INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (research_id, source_version_id)
);

CREATE TABLE record_flags (
  research_id TEXT NOT NULL REFERENCES researches(id),
  scope_revision INTEGER NOT NULL,
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  flag TEXT NOT NULL,
  evidence TEXT NOT NULL,
  step_id TEXT,
  protocol_hash TEXT,
  created_at TEXT NOT NULL,
  PRIMARY KEY (research_id, scope_revision, source_version_id, flag)
);

CREATE TABLE "record_links" (
  id TEXT PRIMARY KEY,
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  other_source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  link_kind TEXT NOT NULL CHECK (link_kind IN ('same_work', 'extended_version', 'probable_version', 'related_suspected',
                                               'artifact_of', 'notice_of')),
  rule TEXT NOT NULL,
  source TEXT NOT NULL CHECK (source IN ('text', 'arxiv_doi', 'semantic_scholar', 'crossref_relation')),
  parent_source_version_id TEXT REFERENCES source_versions(id),
  title_similarity REAL,
  abstract_similarity REAL,
  author_agreement TEXT NOT NULL CHECK (author_agreement IN ('agree', 'differ', 'unknown')),
  year_gap INTEGER,
  merged INTEGER NOT NULL CHECK (merged IN (0, 1)),
  undo_json TEXT,
  closed_at TEXT,
  closed_reason TEXT CHECK (closed_reason IS NULL OR closed_reason IN ('undone', 'superseded')),
  closed_note TEXT,
  created_at TEXT NOT NULL,
  CHECK (source_version_id < other_source_version_id),
  CHECK ((closed_at IS NULL) = (closed_reason IS NULL))
);

CREATE TABLE record_references (
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  referenced_id TEXT NOT NULL,          -- OpenAlex work id, short form (W…)
  PRIMARY KEY (source_version_id, referenced_id)
) WITHOUT ROWID;

CREATE TABLE "record_lookups" (
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  provider TEXT NOT NULL CHECK (provider IN ('semantic_scholar', 'crossref', 'scopus')),
  status TEXT NOT NULL CHECK (status IN ('found', 'not_found', 'failed')),
  had_abstract INTEGER NOT NULL CHECK (had_abstract IN (0, 1)),
  step_id TEXT,
  asked_at TEXT NOT NULL,
  PRIMARY KEY (source_version_id, provider)
);

CREATE TABLE candidate_hits (
  research_id TEXT NOT NULL REFERENCES researches(id),
  scope_revision INTEGER NOT NULL,
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  search_run_id TEXT NOT NULL REFERENCES search_runs(id),
  PRIMARY KEY (source_version_id, search_run_id)
);

CREATE TABLE chain_links (
  research_id TEXT NOT NULL REFERENCES researches(id),
  scope_revision INTEGER NOT NULL,
  run_id TEXT NOT NULL REFERENCES runs(id),
  seed_source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  linked_openalex_id TEXT NOT NULL,     -- OpenAlex work id, short form (W…)
  direction TEXT NOT NULL CHECK (direction IN ('backward', 'forward')),
  passed_filter INTEGER NOT NULL CHECK (passed_filter IN (0, 1)),
  source_version_id TEXT REFERENCES source_versions(id),
  PRIMARY KEY (run_id, seed_source_version_id, linked_openalex_id, direction)
);

CREATE TABLE human_selection_links (
  decision_id TEXT NOT NULL REFERENCES stage_decisions(id),
  research_id TEXT NOT NULL REFERENCES researches(id),
  head TEXT NOT NULL REFERENCES source_versions(id),
  selection_version INTEGER NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE person_pdf_requests (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  asset_id TEXT NOT NULL REFERENCES source_assets(id),
  scope_revision INTEGER NOT NULL,
  criterion_hash TEXT,
  status TEXT NOT NULL CHECK (status IN ('waiting', 'planned', 'read', 'unread')),
  attempt INTEGER NOT NULL DEFAULT 0,
  run_id TEXT REFERENCES runs(id),
  page_digest TEXT,
  decision_id TEXT REFERENCES stage_decisions(id),
  unread_reason TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE scope_english_questions (
  research_id TEXT NOT NULL REFERENCES researches(id),
  scope_revision INTEGER NOT NULL,
  text TEXT NOT NULL,
  origin TEXT NOT NULL CHECK (origin IN ('user', 'question')),
  created_at TEXT NOT NULL,
  PRIMARY KEY (research_id, scope_revision)
);

CREATE TABLE "passages" (
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
  created_at TEXT NOT NULL, text_source TEXT NOT NULL DEFAULT 'text_layer' CHECK (text_source IN ('text_layer', 'ocr', 'marker', 'latex_source')),
  CHECK (kind <> 'abstract' OR (physical_page IS NULL AND abstract_origin IS NOT NULL)),
  CHECK (kind <> 'pdf_page' OR (physical_page IS NOT NULL AND asset_id IS NOT NULL))
);

CREATE TABLE arxiv_sources (
  arxiv_key TEXT PRIMARY KEY,  -- <id>v<N>
  arxiv_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('downloaded', 'version_mismatch', 'too_large', 'unreadable', 'not_settled')),
  content TEXT CHECK (content IS NULL OR content IN ('tex', 'pdf_only', 'no_tex', 'too_large', 'unreadable')),
  sha256 TEXT,
  byte_size INTEGER,
  storage_path TEXT,  -- relative to the data directory
  http_status INTEGER,
  error TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  last_attempt_at TEXT,
  fetched_at TEXT,
  inspected_at TEXT,
  repairs INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE asset_arxiv_versions (
  asset_id TEXT PRIMARY KEY REFERENCES source_assets(id),
  eligibility TEXT NOT NULL CHECK (eligibility IN ('eligible', 'no_version', 'version_conflict', 'record_identity_unknown',
    'record_identity_conflict', 'record_version_conflict')),
  arxiv_key TEXT,
  version_from TEXT CHECK (version_from IS NULL OR version_from IN ('url', 'stamp', 'both')),
  record_label TEXT,
  checked_at TEXT NOT NULL
);

CREATE TABLE "pdf_discovery_runs" (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  provider TEXT NOT NULL CHECK (provider IN ('unpaywall', 'openalex', 'crossref', 'core', 'europepmc', 'web_search')),
  query_text TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'zero_results', 'auth_required', 'rate_limited', 'timeout', 'parse_error', 'failed')),
  result_count INTEGER NOT NULL DEFAULT 0,
  http_status INTEGER,
  error_code TEXT,
  created_at TEXT NOT NULL,
  finished_at TEXT,
  other_title_count INTEGER NOT NULL DEFAULT 0
, retry_after TEXT, attempt_id TEXT);

CREATE TABLE "pdf_candidates" (
  id TEXT PRIMARY KEY,
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  discovery_run_id TEXT NOT NULL REFERENCES "pdf_discovery_runs"(id),
  provider TEXT NOT NULL CHECK (provider IN ('unpaywall', 'openalex', 'crossref', 'core', 'europepmc', 'web_search')),
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

CREATE TABLE report_claim_revisions (
  id TEXT PRIMARY KEY,
  claim_id TEXT NOT NULL REFERENCES report_claims(id),
  kind TEXT NOT NULL CHECK (kind IN ('human_edit', 'human_restore')),
  restored_from TEXT,
  text TEXT NOT NULL,
  warnings_json TEXT NOT NULL DEFAULT '[]',
  note TEXT,
  idempotency_key TEXT UNIQUE,
  created_at TEXT NOT NULL, link_count INTEGER CHECK (link_count >= 0), request_hash TEXT,
  CHECK ((kind = 'human_restore') = (restored_from IS NOT NULL))
);

CREATE TABLE report_stale_acknowledgements (
  id TEXT PRIMARY KEY,
  report_id TEXT NOT NULL REFERENCES reports(id),
  section_id TEXT NOT NULL,
  change_key TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (report_id, section_id, change_key)
);

CREATE TABLE lineage_links (
  id TEXT PRIMARY KEY,
  table_id TEXT NOT NULL REFERENCES evidence_tables(id),
  from_source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  to_source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  current_revision_id TEXT REFERENCES lineage_link_revisions(id),
  version INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  CHECK (from_source_version_id <> to_source_version_id),
  UNIQUE (table_id, from_source_version_id, to_source_version_id)
) WITHOUT ROWID;

CREATE TABLE lineage_link_revisions (
  id TEXT PRIMARY KEY,
  link_id TEXT NOT NULL REFERENCES lineage_links(id),
  kind TEXT NOT NULL CHECK (kind IN ('model_propose', 'human_add', 'human_edit', 'human_remove')),
  author TEXT NOT NULL CHECK (author IN ('model', 'human')),
  decision TEXT NOT NULL CHECK (decision IN ('link', 'no_relation', 'insufficient_evidence', 'removed')),
  disposition TEXT NOT NULL CHECK (disposition IN ('accepted', 'rejected')),
  rejection_code TEXT,
  relation TEXT CHECK (relation IN ('extends', 'relaxes_assumption', 'changes_method',
                                    'new_domain_or_condition', 'corrects_or_contradicts', 'independent_parallel')),
  what_changed TEXT,
  support_type TEXT CHECK (support_type IN ('source_stated', 'analyst_inference')),
  note TEXT,
  origin TEXT NOT NULL CHECK (origin IN ('mention', 'human')),
  edge_state TEXT CHECK (edge_state IN ('present', 'absent_in_read_list', 'unresolved', 'not_read')),
  based_on_revision_id TEXT REFERENCES lineage_link_revisions(id),
  link_version_at_request INTEGER,
  scope_revision INTEGER,
  inputs_json TEXT,
  run_id TEXT REFERENCES runs(id), step_id TEXT REFERENCES run_steps(id), step_input_id TEXT REFERENCES step_inputs(id),
  output_status TEXT CHECK (output_status IN ('structurally_valid', 'unverified_draft')),
  idempotency_key TEXT UNIQUE,
  created_at TEXT NOT NULL,
  CHECK ((kind = 'model_propose') = (author = 'model')),
  CHECK ((decision = 'link' AND relation IS NOT NULL AND what_changed IS NOT NULL AND support_type IS NOT NULL)
         OR (decision <> 'link' AND relation IS NULL AND what_changed IS NULL AND support_type IS NULL)),
  CHECK ((kind = 'human_remove') = (decision = 'removed')),
  CHECK (kind NOT IN ('human_add', 'human_edit') OR decision = 'link'),
  CHECK ((author = 'human') = (origin = 'human')),
  CHECK ((disposition = 'rejected') = (rejection_code IS NOT NULL)),
  CHECK (author <> 'human' OR disposition = 'accepted'),
  CHECK (author <> 'model' OR (step_input_id IS NOT NULL AND output_status IS NOT NULL))
) WITHOUT ROWID;

CREATE TABLE lineage_link_evidence (
  link_revision_id TEXT NOT NULL REFERENCES lineage_link_revisions(id),
  passage_id TEXT NOT NULL REFERENCES passages(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  anchor_text TEXT NOT NULL,
  anchor_match TEXT NOT NULL CHECK (anchor_match IN ('exact', 'normalized', 'fuzzy')),
  PRIMARY KEY (link_revision_id, passage_id, anchor_text)
) WITHOUT ROWID;

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

CREATE TABLE candidate_status_overrides (
  id TEXT PRIMARY KEY,
  candidate_version_id TEXT NOT NULL REFERENCES candidate_versions(id),
  status TEXT NOT NULL CHECK (status IN ('not_run', 'undecided', 'narrowed', 'closed', 'open')),
  reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
  created_at TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE report_edit_checks (
  id TEXT PRIMARY KEY,
  report_id TEXT NOT NULL REFERENCES reports(id),
  checker_version TEXT NOT NULL,
  input_fingerprint TEXT NOT NULL,
  result_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (report_id, input_fingerprint)
);

CREATE TABLE report_claim_revision_links (
  revision_id TEXT NOT NULL REFERENCES report_claim_revisions(id),
  link_id TEXT NOT NULL REFERENCES report_citation_links(id),
  PRIMARY KEY (revision_id, link_id)
) WITHOUT ROWID;

CREATE TABLE owner_review_snapshots (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  target_kind TEXT NOT NULL CHECK (target_kind IN ('answer', 'report', 'candidate')),
  target_id TEXT NOT NULL,
  content_json TEXT NOT NULL,
  content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64),
  markers_json TEXT NOT NULL,
  created_at TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE owner_reviews (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  snapshot_id TEXT NOT NULL REFERENCES owner_review_snapshots(id),
  run_id TEXT NOT NULL UNIQUE REFERENCES runs(id),
  focus TEXT NOT NULL CHECK (focus IN ('source_support', 'assumptions_and_consistency')),
  -- Match Python str.strip() whitespace, including Unicode, at the SQL boundary.
  owner_note TEXT CHECK (owner_note IS NULL OR (length(owner_note) <= 500 AND length(trim(owner_note, char(9,10,11,12,13,28,29,30,31,32,133,160,5760,8192,8193,8194,8195,8196,8197,8198,8199,8200,8201,8202,8232,8233,8239,8287,12288))) > 0)),
  requested_connection TEXT NOT NULL,
  requested_model TEXT,
  requested_effort TEXT,
  failure_reason TEXT,
  sections_not_reviewed_json TEXT NOT NULL DEFAULT '[]',
  idempotency_key TEXT UNIQUE,
  created_at TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE owner_review_findings (
  id TEXT PRIMARY KEY,
  review_id TEXT NOT NULL REFERENCES owner_reviews(id),
  ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
  finding_json TEXT NOT NULL,
  step_input_id TEXT NOT NULL REFERENCES step_inputs(id),
  UNIQUE (review_id, ordinal)
) WITHOUT ROWID;

CREATE TABLE owner_review_decisions (
  id TEXT PRIMARY KEY,
  finding_id TEXT NOT NULL REFERENCES owner_review_findings(id),
  ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
  decision TEXT NOT NULL CHECK (decision IN ('accepted', 'dismissed', 'deferred')),
  reason TEXT,
  applied_ref TEXT,
  created_at TEXT NOT NULL, idempotency_key TEXT, request_hash TEXT,
  UNIQUE (finding_id, ordinal),
  CHECK (decision != 'dismissed' OR (reason IS NOT NULL AND length(trim(reason, char(9,10,11,12,13,28,29,30,31,32,133,160,5760,8192,8193,8194,8195,8196,8197,8198,8199,8200,8201,8202,8232,8233,8239,8287,12288))) > 0)),
  CHECK (applied_ref IS NULL OR decision = 'accepted')
) WITHOUT ROWID;

CREATE TABLE asset_recovery_operations (
  id TEXT NOT NULL PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('file_restore', 'text_retry')),
  asset_id TEXT REFERENCES source_assets(id),
  research_id TEXT,
  expected_sha256 TEXT NOT NULL CHECK (length(expected_sha256) = 64),
  expected_byte_size INTEGER NOT NULL,
  baseline_extraction_id TEXT REFERENCES asset_extractions(id) DEFERRABLE INITIALLY DEFERRED,
  baseline_profile TEXT,
  mode TEXT CHECK (mode IS NULL OR mode = 'retry_failed_or_partial'),
  idempotency_key TEXT NOT NULL UNIQUE,
  request_fingerprint TEXT NOT NULL,
  lifecycle TEXT NOT NULL CHECK (lifecycle IN ('running', 'completed', 'interrupted')),
  outcome TEXT CHECK (outcome IN ('promoted', 'diagnosis_updated', 'rejected', 'no_change', 'refused', 'file_reused', 'file_restored', 'file_refused')),
  reason TEXT,
  decision_code TEXT CHECK (decision_code IS NULL OR decision_code IN ('no_change', 'recovered_text', 'password_diagnosed', 'no_text_diagnosed', 'text_updated', 'recovered_from_corrupt_input', 'candidate_failed', 'augmented_text_would_be_lost', 'status_worse', 'page_count_changed', 'legacy_page_count_untrusted', 'text_page_lost', 'upgraded', 'fewer_text_pages', 'ocr_found_no_text', 'input_not_verified')),
  before_observation_id TEXT REFERENCES asset_file_observations(id) DEFERRABLE INITIALLY DEFERRED,
  after_observation_id TEXT REFERENCES asset_file_observations(id) DEFERRABLE INITIALLY DEFERRED,
  input_observation_id TEXT REFERENCES asset_file_observations(id) DEFERRABLE INITIALLY DEFERRED,
  old_coverage_json TEXT,
  new_coverage_json TEXT,
  created_at TEXT NOT NULL,
  finished_at TEXT,
  CHECK (kind <> 'text_retry' OR (asset_id IS NOT NULL AND mode IS NOT NULL AND baseline_extraction_id IS NOT NULL AND baseline_profile IS NOT NULL)),
  CHECK ((finished_at IS NULL) = (lifecycle = 'running')),
  CHECK ((outcome IS NOT NULL) = (lifecycle = 'completed'))
) WITHOUT ROWID;

CREATE TABLE asset_file_observations (
  id TEXT NOT NULL PRIMARY KEY,
  operation_id TEXT REFERENCES asset_recovery_operations(id),
  kind TEXT NOT NULL CHECK (kind IN ('before_restore', 'after_restore', 'extraction_input')),
  storage_path TEXT NOT NULL,
  expected_sha256 TEXT NOT NULL CHECK (length(expected_sha256) = 64),
  expected_byte_size INTEGER NOT NULL,
  observed_sha256 TEXT,
  observed_byte_size INTEGER,
  integrity TEXT NOT NULL CHECK (integrity IN ('verified', 'mismatch', 'missing', 'legacy_unknown')),
  retained_filename TEXT,
  observed_at TEXT NOT NULL,
  CHECK (
    (integrity = 'verified' AND observed_sha256 IS NOT NULL AND observed_byte_size IS NOT NULL
      AND observed_sha256 = expected_sha256 AND observed_byte_size = expected_byte_size)
    OR (integrity = 'mismatch' AND observed_sha256 IS NOT NULL AND observed_byte_size IS NOT NULL
      AND (observed_sha256 <> expected_sha256 OR observed_byte_size <> expected_byte_size))
    OR (integrity IN ('missing', 'legacy_unknown') AND observed_sha256 IS NULL AND observed_byte_size IS NULL)
  ),
  CHECK (retained_filename IS NULL OR (kind = 'before_restore' AND observed_sha256 IS NOT NULL))
) WITHOUT ROWID;

CREATE TABLE watches (
 id TEXT PRIMARY KEY, research_id TEXT NOT NULL REFERENCES researches(id),
 kind TEXT NOT NULL CHECK (kind IN ('protocol_queries','citing_works')),
 mode TEXT NOT NULL DEFAULT 'manual' CHECK (mode IN ('manual','interval')),
 interval_days INTEGER CHECK (interval_days IS NULL OR interval_days IN (1,7,30)),
 enabled INTEGER NOT NULL CHECK (enabled IN (0,1)),
 protocol_record_id TEXT REFERENCES protocol_records(id), scope_revision INTEGER NOT NULL,
 baseline_json TEXT NOT NULL DEFAULT '{}', state_version INTEGER NOT NULL DEFAULT 1,
 last_checked_at TEXT, last_success_at TEXT, next_due_at TEXT,
 idempotency_key TEXT UNIQUE, request_hash TEXT, disable_key TEXT UNIQUE, disable_hash TEXT,
 created_at TEXT NOT NULL, disabled_at TEXT
, catch_up INTEGER CHECK (catch_up IS NULL OR catch_up IN (0,1)), schedule_version INTEGER NOT NULL DEFAULT 1 CHECK (schedule_version >= 1));

CREATE TABLE watch_checks (
 id TEXT PRIMARY KEY, watch_id TEXT NOT NULL REFERENCES watches(id),
 research_id TEXT NOT NULL REFERENCES researches(id), run_id TEXT NOT NULL UNIQUE REFERENCES runs(id),
 trigger TEXT NOT NULL CHECK (trigger IN ('manual','scheduled','catch_up')),
 period_start TEXT NOT NULL, requested_from TEXT, requested_to TEXT NOT NULL,
 config_json TEXT NOT NULL, state_version INTEGER NOT NULL, missed_periods INTEGER NOT NULL DEFAULT 0,
 request_key TEXT UNIQUE, request_hash TEXT, observed_json TEXT, provider_status_json TEXT,
 counts_json TEXT, completed_at TEXT, created_at TEXT NOT NULL, UNIQUE(watch_id,period_start)
) WITHOUT ROWID;

CREATE TABLE watch_reads (
 id TEXT PRIMARY KEY, check_id TEXT NOT NULL REFERENCES watch_checks(id),
 research_id TEXT NOT NULL REFERENCES researches(id), step_id TEXT NOT NULL UNIQUE REFERENCES run_steps(id),
 unit_key TEXT NOT NULL, page_number INTEGER NOT NULL, provider TEXT NOT NULL,
 status TEXT NOT NULL, error_code TEXT, request_description TEXT NOT NULL,
 http_status INTEGER, error_kind TEXT, returned_count INTEGER NOT NULL, dropped_count INTEGER NOT NULL,
 next_cursor TEXT, oldest_publication_date TEXT, newest_publication_date TEXT,
 records_json TEXT NOT NULL, connector_json TEXT, raw_payload_path TEXT,
 payload_sha256 TEXT, payload_file_sha256 TEXT, created_at TEXT NOT NULL,
 UNIQUE(check_id,unit_key,page_number)
) WITHOUT ROWID;

CREATE TABLE watch_seen (
 id TEXT PRIMARY KEY, research_id TEXT NOT NULL REFERENCES researches(id), identity_key TEXT NOT NULL,
 record_json TEXT NOT NULL, merged_into TEXT REFERENCES watch_seen(id),
 first_seen_check_id TEXT NOT NULL REFERENCES watch_checks(id),
 origin TEXT NOT NULL CHECK (origin IN ('baseline','baseline_undated','announced','in_library','notice')),
 identity_uncertain INTEGER NOT NULL CHECK (identity_uncertain IN (0,1)), created_at TEXT NOT NULL
);

CREATE TABLE watch_seen_alias (
 research_id TEXT NOT NULL REFERENCES researches(id), alias TEXT NOT NULL,
 seen_id TEXT NOT NULL REFERENCES watch_seen(id), created_at TEXT NOT NULL,
 UNIQUE(research_id,alias)
);

CREATE TABLE watch_items (
 id TEXT PRIMARY KEY, research_id TEXT NOT NULL REFERENCES researches(id),
 check_id TEXT NOT NULL REFERENCES watch_checks(id), seen_id TEXT NOT NULL REFERENCES watch_seen(id),
 record_json TEXT NOT NULL, kind TEXT NOT NULL CHECK (kind IN ('new_record','notice')),
 found_by_json TEXT NOT NULL, relations_json TEXT NOT NULL, kind_history_json TEXT NOT NULL,
 status TEXT NOT NULL CHECK (status IN ('new','dismissed','added','merged')),
 merged_into_item_id TEXT REFERENCES watch_items(id), dismissed_reason TEXT, dismissed_at TEXT,
 dismiss_key TEXT UNIQUE, dismiss_hash TEXT, created_at TEXT NOT NULL, UNIQUE(research_id,seen_id)
);

CREATE TABLE recovery_purge_authorizations (sha256 TEXT PRIMARY KEY) WITHOUT ROWID;

CREATE TABLE watch_schedule_changes (
 id TEXT PRIMARY KEY, watch_id TEXT NOT NULL REFERENCES watches(id), research_id TEXT NOT NULL REFERENCES researches(id),
 schedule_version INTEGER NOT NULL CHECK (schedule_version >= 2),
 mode TEXT NOT NULL CHECK (mode IN ('manual','interval')),
 interval_days INTEGER CHECK (interval_days IS NULL OR interval_days IN (1,7,30)),
 catch_up INTEGER CHECK (catch_up IS NULL OR catch_up IN (0,1)), next_due_at TEXT,
 request_key TEXT NOT NULL UNIQUE, request_hash TEXT NOT NULL, created_at TEXT NOT NULL,
 UNIQUE(watch_id,schedule_version),
 CHECK ((mode='manual' AND interval_days IS NULL AND catch_up IS NULL AND next_due_at IS NULL)
     OR (mode='interval' AND interval_days IS NOT NULL AND catch_up IS NOT NULL AND next_due_at IS NOT NULL))
) WITHOUT ROWID;

CREATE TABLE watch_gaps (
 id TEXT PRIMARY KEY, watch_id TEXT NOT NULL REFERENCES watches(id), research_id TEXT NOT NULL REFERENCES researches(id),
 opening_id TEXT NOT NULL, first_missed_due TEXT NOT NULL, last_missed_due TEXT NOT NULL,
 missed_periods INTEGER NOT NULL CHECK (missed_periods >= 1), observed_until TEXT, noticed_at TEXT NOT NULL,
 schedule_version INTEGER NOT NULL CHECK (schedule_version >= 1),
 outcome TEXT NOT NULL CHECK (outcome IN ('catch_up_chosen','catch_up_off','opening_cap','one_per_research','not_eligible','changed_before_record')),
 outcome_reason TEXT, next_due_at TEXT, created_at TEXT NOT NULL, UNIQUE(watch_id,opening_id)
) WITHOUT ROWID;

CREATE TABLE openalex_budget_runs (
  run_id TEXT PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
  research_id TEXT NOT NULL REFERENCES researches(id) ON DELETE CASCADE,
  reset_at TEXT NOT NULL,
  refused INTEGER NOT NULL DEFAULT 0,
  skipped INTEGER NOT NULL DEFAULT 0,
  event_id INTEGER NOT NULL
);

CREATE TABLE fast_path_ledgers (
    ledger_run_id TEXT PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
    research_id TEXT NOT NULL REFERENCES researches(id) ON DELETE CASCADE,
    scope_revision INTEGER NOT NULL,
    policy TEXT NOT NULL,
    policy_hash TEXT NOT NULL,
    mode TEXT NOT NULL,
    started_at TEXT NOT NULL,
    answer_run_id TEXT REFERENCES runs(id) ON DELETE SET NULL,
    answer_published_at TEXT,
    answer_outcome TEXT
);

CREATE TABLE fast_path_stages (
    ledger_run_id TEXT NOT NULL REFERENCES fast_path_ledgers(ledger_run_id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    seq INTEGER NOT NULL,
    base_ms INTEGER NOT NULL,
    balance_before_ms INTEGER NOT NULL,
    alloc_ms INTEGER NOT NULL,
    opened_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('open', 'done', 'skipped')),
    done_at TEXT,
    used_ms INTEGER NOT NULL DEFAULT 0,
    rework_ms INTEGER NOT NULL DEFAULT 0,
    overrun_ms INTEGER NOT NULL DEFAULT 0,
    done_generation INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (ledger_run_id, stage)
);

CREATE TABLE fast_path_intervals (
    id TEXT PRIMARY KEY,
    ledger_run_id TEXT NOT NULL REFERENCES fast_path_ledgers(ledger_run_id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    generation INTEGER NOT NULL,
    rework INTEGER NOT NULL CHECK (rework IN (0, 1)),
    started_at TEXT NOT NULL,
    last_checkpoint_at TEXT NOT NULL,
    max_checkpoint_gap_ms INTEGER NOT NULL DEFAULT 0,
    closed_at TEXT,
    close_reason TEXT CHECK (close_reason IN ('stage_done', 'paused', 'stopped', 'recovered')),
    UNIQUE (run_id, stage, attempt)
);

CREATE TABLE fast_path_background_fetches (
    id TEXT PRIMARY KEY,
    ledger_run_id TEXT NOT NULL REFERENCES fast_path_ledgers(ledger_run_id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    research_id TEXT NOT NULL REFERENCES researches(id) ON DELETE CASCADE,
    scope_revision INTEGER NOT NULL,
    work_id TEXT NOT NULL,
    head TEXT NOT NULL,
    position INTEGER NOT NULL,
    origin TEXT NOT NULL CHECK (origin IN ('in_flight', 'not_started')),
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    attempts INTEGER NOT NULL DEFAULT 0,
    queued_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    outcome_code TEXT,
    UNIQUE (run_id, work_id)
);

CREATE TABLE fast_path_embedding_queue (
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    class INTEGER NOT NULL CHECK (class IN (0, 1, 2)),
    request_index INTEGER NOT NULL,
    position INTEGER NOT NULL,
    source_version_id TEXT NOT NULL REFERENCES source_versions(id) ON DELETE CASCADE,
    search_run_id TEXT REFERENCES search_runs(id) ON DELETE SET NULL,
    enqueued_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'embedded', 'from_store', 'unembedded_at_cutoff')),
    embedded_at TEXT,
    cutoff_at TEXT,
    PRIMARY KEY (run_id, class, request_index, position),
    UNIQUE (run_id, source_version_id)
);

CREATE TABLE "runs" (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  scope_revision INTEGER NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('discovery', 'answer', 'answer_review', 'table_columns', 'table_fill', 'cell_recheck', 'research_title', 'pdf_collection', 'pdf_ocr', 'report', 'fulltext_fetch', 'fulltext_adjudication', 'lineage_links', 'claim_decomposition', 'kill_search', 'review', 'watch_check')),
  status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'pause_requested', 'paused', 'completed', 'failed', 'cancelled')),
  stage TEXT NOT NULL CHECK (stage IN ('intake', 'discovery', 'screening', 'inspection', 'answer', 'extraction', 'synthesis', 'candidate', 'claim_check', 'export')),
  pause_reason TEXT, error_json TEXT,
  budget_json TEXT NOT NULL, usage_json TEXT NOT NULL DEFAULT '{}',
  idempotency_key TEXT UNIQUE,
  target_json TEXT,
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);

CREATE TABLE fast_path_late_revisions (
    id TEXT PRIMARY KEY,
    ledger_run_id TEXT NOT NULL UNIQUE REFERENCES runs(id) ON DELETE CASCADE,
    research_id TEXT NOT NULL REFERENCES researches(id) ON DELETE CASCADE,
    scope_revision INTEGER NOT NULL,
    base_answer_id TEXT NOT NULL REFERENCES answers(id) ON DELETE CASCADE,
    base_input_step_id TEXT NOT NULL REFERENCES run_steps(id),
    status TEXT NOT NULL CHECK(status IN ('waiting_fetch','reading','answering','published','skipped','failed')),
    skip_reason TEXT,
    read_run_id TEXT REFERENCES runs(id),
    answer_run_id TEXT REFERENCES runs(id),
    revision_answer_id TEXT REFERENCES answers(id),
    works_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    read_started_at TEXT,
    published_at TEXT
);

CREATE INDEX events_research ON events(research_id, id);

CREATE INDEX identifier_lookup ON identifier_mappings(scheme, value);

CREATE INDEX evidence_tables_research ON evidence_tables(research_id, created_at);

CREATE INDEX cell_revisions_cell ON cell_revisions(cell_id, created_at);

CREATE UNIQUE INDEX answers_report_version ON answers (research_id, report_version) WHERE report_version IS NOT NULL;

CREATE UNIQUE INDEX cell_evidence_links_anchor ON cell_evidence_links (cell_revision_id, passage_id, IFNULL(anchor_text, ''));

CREATE UNIQUE INDEX source_assets_one_in_use ON source_assets(source_version_id) WHERE removed_at IS NULL;

CREATE UNIQUE INDEX asset_extractions_one_current ON asset_extractions(asset_id) WHERE outcome = 'current';

CREATE INDEX corpus_memberships_active ON corpus_memberships (research_id) WHERE removed_at IS NULL;

CREATE UNIQUE INDEX works_source_key ON works (source_key COLLATE NOCASE) WHERE source_key IS NOT NULL;

CREATE UNIQUE INDEX reports_report_version ON reports (research_id, report_version) WHERE report_version IS NOT NULL;

CREATE INDEX reports_research ON reports (research_id, created_at);

CREATE INDEX report_claim_refs_claim ON report_claim_refs (claim_id);

CREATE INDEX report_citation_links_claim ON report_citation_links (claim_id);

CREATE INDEX report_phrase_repairs_report ON report_phrase_repairs (report_id);

CREATE INDEX protocol_records_scope ON protocol_records(research_id, scope_revision, protocol_revision);

CREATE UNIQUE INDEX stage_decisions_current ON stage_decisions(research_id, source_version_id, stage) WHERE superseded_at IS NULL;

CREATE INDEX stage_decisions_research ON stage_decisions(research_id, stage, outcome);

CREATE INDEX model_proposals_record ON model_proposals(research_id, source_version_id, stage, run_no);

CREATE INDEX record_signal_ranks_research ON record_signal_ranks(research_id, signal, rank);

CREATE UNIQUE INDEX record_links_open ON record_links(source_version_id, other_source_version_id) WHERE closed_at IS NULL;

CREATE INDEX record_links_other ON record_links(other_source_version_id);

CREATE INDEX source_versions_work_id ON source_versions(work_id);

CREATE INDEX candidate_hits_research ON candidate_hits (research_id, scope_revision);

CREATE INDEX chain_links_research ON chain_links (research_id, scope_revision);

CREATE INDEX human_selection_links_decision ON human_selection_links(decision_id);

CREATE INDEX human_selection_links_research ON human_selection_links(research_id, head);

CREATE UNIQUE INDEX person_pdf_requests_file ON person_pdf_requests(research_id, asset_id);

CREATE INDEX person_pdf_requests_state ON person_pdf_requests(research_id, status);

CREATE INDEX person_pdf_requests_run ON person_pdf_requests(run_id);

CREATE INDEX passages_source ON passages(source_version_id);

CREATE INDEX pdf_discovery_source ON pdf_discovery_runs(source_version_id, created_at);

CREATE INDEX pdf_candidates_source ON pdf_candidates(source_version_id, discovered_at);

CREATE INDEX report_claim_revisions_claim ON report_claim_revisions(claim_id, created_at);

CREATE UNIQUE INDEX table_columns_lineage_role ON table_columns (table_id, lineage_role)
  WHERE lineage_role IS NOT NULL AND removed_at IS NULL;

CREATE INDEX lineage_link_revisions_link ON lineage_link_revisions(link_id, created_at);

CREATE UNIQUE INDEX research_candidates_gap ON research_candidates(research_id, origin_gap_row_id, origin_fingerprint)
  WHERE origin_gap_row_id IS NOT NULL;

CREATE INDEX research_candidates_research ON research_candidates(research_id, created_at, id);

CREATE INDEX kill_searches_version ON kill_searches(candidate_version_id, created_at, id);

CREATE INDEX kill_search_query_records_source ON kill_search_query_records(source_version_id);

CREATE INDEX kill_search_hits_source ON kill_search_hits(source_version_id);

CREATE INDEX claim_matrix_cells_source ON claim_matrix_cells(source_version_id);

CREATE INDEX claim_matrix_evidence_search ON claim_matrix_evidence(kill_search_id, source_version_id);

CREATE INDEX claim_matrix_evidence_passage ON claim_matrix_evidence(passage_id);

CREATE INDEX claim_matrix_evidence_source ON claim_matrix_evidence(source_version_id);

CREATE INDEX candidate_status_overrides_version ON candidate_status_overrides(candidate_version_id, created_at, id);

CREATE INDEX identifier_mappings_view_lookup ON identifier_mappings(source_version_id, provider, scheme);

CREATE INDEX run_steps_operation ON run_steps(operation_key, started_at);

CREATE INDEX source_assets_replaced ON source_assets(source_version_id, removed_at) WHERE removal_reason = 'replaced';

CREATE INDEX passages_asset ON passages(asset_id, kind);

CREATE INDEX owner_review_snapshots_target ON owner_review_snapshots(research_id, target_kind, target_id, created_at);

CREATE INDEX owner_reviews_research ON owner_reviews(research_id, created_at);

CREATE INDEX owner_reviews_snapshot ON owner_reviews(snapshot_id, created_at);

CREATE INDEX owner_review_findings_review ON owner_review_findings(review_id);

CREATE INDEX owner_review_decisions_finding ON owner_review_decisions(finding_id, created_at);

CREATE UNIQUE INDEX owner_review_decisions_request ON owner_review_decisions(idempotency_key);

CREATE INDEX asset_recovery_operations_asset_created ON asset_recovery_operations(asset_id, created_at);

CREATE UNIQUE INDEX asset_recovery_operations_one_running ON asset_recovery_operations(asset_id)
  WHERE kind = 'text_retry' AND lifecycle = 'running';

CREATE INDEX asset_file_observations_operation ON asset_file_observations(operation_id);

CREATE UNIQUE INDEX asset_extractions_recovery_operation ON asset_extractions(recovery_operation_id)
  WHERE recovery_operation_id IS NOT NULL;

CREATE UNIQUE INDEX watches_enabled_kind ON watches(research_id,kind) WHERE enabled = 1;

CREATE INDEX watch_reads_check ON watch_reads(check_id,unit_key,page_number);

CREATE INDEX watch_seen_research ON watch_seen(research_id,created_at,id);

CREATE INDEX watch_items_research ON watch_items(research_id,status,created_at,id);

CREATE UNIQUE INDEX pdf_discovery_attempt ON pdf_discovery_runs(attempt_id) WHERE attempt_id IS NOT NULL;

CREATE UNIQUE INDEX fast_path_interval_open ON fast_path_intervals(run_id, stage) WHERE closed_at IS NULL;

CREATE INDEX fast_path_background_ready ON fast_path_background_fetches(status, queued_at, position);

CREATE INDEX fast_path_embedding_pending ON fast_path_embedding_queue(run_id, status, class, request_index, position);

CREATE INDEX runs_status ON runs(status, created_at);

CREATE INDEX fast_path_late_revision_open ON fast_path_late_revisions(research_id, status);

CREATE TRIGGER step_inputs_no_update BEFORE UPDATE ON step_inputs
BEGIN SELECT RAISE(ABORT, 'step_inputs are immutable'); END;

CREATE TRIGGER step_inputs_no_delete BEFORE DELETE ON step_inputs
WHEN NOT EXISTS (SELECT 1 FROM research_purge_authorizations WHERE research_id = OLD.research_id)
BEGIN SELECT RAISE(ABORT, 'step_inputs are immutable'); END;

CREATE TRIGGER column_revisions_no_update BEFORE UPDATE ON column_revisions
BEGIN SELECT RAISE(ABORT, 'column revisions are immutable'); END;

CREATE TRIGGER cell_revisions_no_update BEFORE UPDATE ON cell_revisions
BEGIN SELECT RAISE(ABORT, 'cell revisions are immutable'); END;

CREATE TRIGGER cell_evidence_links_no_update BEFORE UPDATE ON cell_evidence_links
BEGIN SELECT RAISE(ABORT, 'cell evidence links are immutable'); END;

CREATE TRIGGER column_revisions_no_delete BEFORE DELETE ON column_revisions
WHEN NOT EXISTS (SELECT 1 FROM table_columns c JOIN evidence_tables t ON t.id = c.table_id
                 JOIN research_purge_authorizations a ON a.research_id = t.research_id WHERE c.id = OLD.column_id)
 AND NOT EXISTS (SELECT 1 FROM table_columns c JOIN table_purge_authorizations a ON a.table_id = c.table_id WHERE c.id = OLD.column_id)
BEGIN SELECT RAISE(ABORT, 'column revisions are immutable'); END;

CREATE TRIGGER cell_revisions_no_delete BEFORE DELETE ON cell_revisions
WHEN NOT EXISTS (SELECT 1 FROM evidence_cells c JOIN evidence_tables t ON t.id = c.table_id
                 JOIN research_purge_authorizations a ON a.research_id = t.research_id WHERE c.id = OLD.cell_id)
 AND NOT EXISTS (SELECT 1 FROM evidence_cells c JOIN table_purge_authorizations a ON a.table_id = c.table_id WHERE c.id = OLD.cell_id)
BEGIN SELECT RAISE(ABORT, 'cell revisions are immutable'); END;

CREATE TRIGGER cell_evidence_links_no_delete BEFORE DELETE ON cell_evidence_links
WHEN NOT EXISTS (SELECT 1 FROM cell_revisions r JOIN evidence_cells c ON c.id = r.cell_id JOIN evidence_tables t ON t.id = c.table_id
                 JOIN research_purge_authorizations a ON a.research_id = t.research_id WHERE r.id = OLD.cell_revision_id)
 AND NOT EXISTS (SELECT 1 FROM cell_revisions r JOIN evidence_cells c ON c.id = r.cell_id
                 JOIN table_purge_authorizations a ON a.table_id = c.table_id WHERE r.id = OLD.cell_revision_id)
BEGIN SELECT RAISE(ABORT, 'cell evidence links are immutable'); END;

CREATE TRIGGER protocol_records_no_update BEFORE UPDATE ON protocol_records
BEGIN SELECT RAISE(ABORT, 'protocol_records are immutable'); END;

CREATE TRIGGER protocol_records_no_delete BEFORE DELETE ON protocol_records
WHEN NOT EXISTS (SELECT 1 FROM research_purge_authorizations WHERE research_id = OLD.research_id)
BEGIN SELECT RAISE(ABORT, 'protocol_records are immutable'); END;

CREATE TRIGGER stage_decisions_no_delete BEFORE DELETE ON stage_decisions
WHEN NOT EXISTS (SELECT 1 FROM research_purge_authorizations WHERE research_id = OLD.research_id)
BEGIN SELECT RAISE(ABORT, 'stage_decisions are kept'); END;

CREATE TRIGGER model_proposals_no_delete BEFORE DELETE ON model_proposals
WHEN NOT EXISTS (SELECT 1 FROM research_purge_authorizations WHERE research_id = OLD.research_id)
BEGIN SELECT RAISE(ABORT, 'model_proposals are kept'); END;

CREATE TRIGGER human_selection_links_no_update BEFORE UPDATE ON human_selection_links
BEGIN SELECT RAISE(ABORT, 'human_selection_links are added, never edited'); END;

CREATE TRIGGER human_selection_links_no_delete BEFORE DELETE ON human_selection_links
WHEN NOT EXISTS (SELECT 1 FROM research_purge_authorizations WHERE research_id = OLD.research_id)
BEGIN SELECT RAISE(ABORT, 'human_selection_links are kept'); END;

CREATE TRIGGER passages_fts_insert AFTER INSERT ON passages
BEGIN INSERT INTO passages_fts(rowid, text) VALUES (new.rowid, new.text); END;

CREATE TRIGGER cell_evidence_same_source BEFORE INSERT ON cell_evidence_links
WHEN NEW.source_version_id IS NOT (SELECT c.source_version_id FROM cell_revisions r JOIN evidence_cells c ON c.id = r.cell_id WHERE r.id = NEW.cell_revision_id)
  OR NEW.source_version_id IS NOT (SELECT source_version_id FROM passages WHERE id = NEW.passage_id)
BEGIN SELECT RAISE(ABORT, 'cell evidence must come from the cell source version'); END;

CREATE TRIGGER report_claim_revisions_no_update BEFORE UPDATE ON report_claim_revisions
BEGIN SELECT RAISE(ABORT, 'report claim revisions are immutable'); END;

CREATE TRIGGER report_claim_revisions_no_delete BEFORE DELETE ON report_claim_revisions
WHEN NOT EXISTS (SELECT 1 FROM report_claims c JOIN report_sections s ON s.id = c.report_section_id
                 JOIN reports r ON r.id = s.report_id JOIN research_purge_authorizations a ON a.research_id = r.research_id
                 WHERE c.id = OLD.claim_id)
BEGIN SELECT RAISE(ABORT, 'report claim revisions are immutable'); END;

CREATE TRIGGER report_stale_acknowledgements_no_update BEFORE UPDATE ON report_stale_acknowledgements
BEGIN SELECT RAISE(ABORT, 'report stale acknowledgements are immutable'); END;

CREATE TRIGGER report_stale_acknowledgements_no_delete BEFORE DELETE ON report_stale_acknowledgements
WHEN NOT EXISTS (SELECT 1 FROM reports r JOIN research_purge_authorizations a ON a.research_id = r.research_id
                 WHERE r.id = OLD.report_id)
BEGIN SELECT RAISE(ABORT, 'report stale acknowledgements are immutable'); END;

CREATE TRIGGER lineage_link_revisions_no_conflicting_insert BEFORE INSERT ON lineage_link_revisions
WHEN EXISTS (SELECT 1 FROM lineage_link_revisions WHERE id = NEW.id)
  OR (NEW.idempotency_key IS NOT NULL AND EXISTS (
      SELECT 1 FROM lineage_link_revisions WHERE idempotency_key = NEW.idempotency_key))
BEGIN SELECT RAISE(ABORT, 'lineage revision already exists'); END;

CREATE TRIGGER lineage_link_evidence_no_conflicting_insert BEFORE INSERT ON lineage_link_evidence
WHEN EXISTS (SELECT 1 FROM lineage_link_evidence WHERE link_revision_id = NEW.link_revision_id
             AND passage_id = NEW.passage_id AND anchor_text = NEW.anchor_text)
BEGIN SELECT RAISE(ABORT, 'lineage evidence already exists'); END;

CREATE TRIGGER lineage_links_no_conflicting_insert BEFORE INSERT ON lineage_links
WHEN EXISTS (SELECT 1 FROM lineage_links WHERE id = NEW.id)
  OR EXISTS (SELECT 1 FROM lineage_links WHERE table_id = NEW.table_id
             AND from_source_version_id = NEW.from_source_version_id AND to_source_version_id = NEW.to_source_version_id)
BEGIN SELECT RAISE(ABORT, 'lineage pair already exists'); END;

CREATE TRIGGER lineage_link_evidence_same_source BEFORE INSERT ON lineage_link_evidence
WHEN NEW.source_version_id IS NOT (SELECT source_version_id FROM passages WHERE id = NEW.passage_id)
  OR NEW.source_version_id IS NOT (SELECT l.to_source_version_id FROM lineage_link_revisions r
                                   JOIN lineage_links l ON l.id = r.link_id WHERE r.id = NEW.link_revision_id)
BEGIN SELECT RAISE(ABORT, 'lineage evidence must come from the later work'); END;

CREATE TRIGGER lineage_link_revisions_no_update BEFORE UPDATE ON lineage_link_revisions
BEGIN SELECT RAISE(ABORT, 'lineage revisions are immutable'); END;

CREATE TRIGGER lineage_link_evidence_no_update BEFORE UPDATE ON lineage_link_evidence
BEGIN SELECT RAISE(ABORT, 'lineage evidence is immutable'); END;

CREATE TRIGGER lineage_link_revisions_no_delete BEFORE DELETE ON lineage_link_revisions
WHEN NOT EXISTS (SELECT 1 FROM lineage_links l JOIN evidence_tables t ON t.id = l.table_id
                 JOIN research_purge_authorizations a ON a.research_id = t.research_id WHERE l.id = OLD.link_id)
 AND NOT EXISTS (SELECT 1 FROM lineage_links l JOIN table_purge_authorizations a ON a.table_id = l.table_id
                 WHERE l.id = OLD.link_id)
BEGIN SELECT RAISE(ABORT, 'lineage revisions are immutable'); END;

CREATE TRIGGER lineage_link_evidence_no_delete BEFORE DELETE ON lineage_link_evidence
WHEN NOT EXISTS (SELECT 1 FROM lineage_link_revisions r JOIN lineage_links l ON l.id = r.link_id
                 JOIN evidence_tables t ON t.id = l.table_id JOIN research_purge_authorizations a ON a.research_id = t.research_id
                 WHERE r.id = OLD.link_revision_id)
 AND NOT EXISTS (SELECT 1 FROM lineage_link_revisions r JOIN lineage_links l ON l.id = r.link_id
                 JOIN table_purge_authorizations a ON a.table_id = l.table_id WHERE r.id = OLD.link_revision_id)
BEGIN SELECT RAISE(ABORT, 'lineage evidence is immutable'); END;

CREATE TRIGGER lineage_links_empty_pointer BEFORE INSERT ON lineage_links
WHEN NEW.current_revision_id IS NOT NULL
BEGIN SELECT RAISE(ABORT, 'a lineage pair starts without a current decision'); END;

CREATE TRIGGER lineage_links_publish_guard BEFORE UPDATE OF current_revision_id ON lineage_links
WHEN NEW.current_revision_id IS NOT NULL AND NOT EXISTS (
  SELECT 1 FROM lineage_link_revisions r WHERE r.id = NEW.current_revision_id AND r.link_id = NEW.id
    AND r.disposition = 'accepted' AND (r.author <> 'model' OR r.output_status = 'structurally_valid')
    AND (r.decision <> 'link' OR EXISTS (SELECT 1 FROM lineage_link_evidence e WHERE e.link_revision_id = r.id))
)
BEGIN SELECT RAISE(ABORT, 'lineage current decision is not publishable'); END;

CREATE TRIGGER lineage_links_identity_no_update
BEFORE UPDATE OF table_id, from_source_version_id, to_source_version_id ON lineage_links
WHEN NEW.table_id IS NOT OLD.table_id OR NEW.from_source_version_id IS NOT OLD.from_source_version_id
  OR NEW.to_source_version_id IS NOT OLD.to_source_version_id
BEGIN SELECT RAISE(ABORT, 'lineage pair identity is immutable'); END;

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

CREATE TRIGGER report_edit_checks_no_update BEFORE UPDATE ON report_edit_checks
BEGIN SELECT RAISE(ABORT, 'report edit checks are immutable'); END;

CREATE TRIGGER report_edit_checks_no_delete BEFORE DELETE ON report_edit_checks
WHEN NOT EXISTS (SELECT 1 FROM reports r JOIN research_purge_authorizations a ON a.research_id = r.research_id
                 WHERE r.id = OLD.report_id)
BEGIN SELECT RAISE(ABORT, 'report edit checks are immutable'); END;

CREATE TRIGGER report_claim_revisions_no_conflicting_insert BEFORE INSERT ON report_claim_revisions
WHEN EXISTS (SELECT 1 FROM report_claim_revisions WHERE id = NEW.id OR rowid = NEW.rowid)
  OR (NEW.idempotency_key IS NOT NULL AND EXISTS (
      SELECT 1 FROM report_claim_revisions WHERE idempotency_key = NEW.idempotency_key))
BEGIN SELECT RAISE(ABORT, 'report claim revision already exists'); END;

CREATE TRIGGER report_claim_revision_links_no_conflicting_insert BEFORE INSERT ON report_claim_revision_links
WHEN EXISTS (SELECT 1 FROM report_claim_revision_links
             WHERE revision_id = NEW.revision_id AND link_id = NEW.link_id)
BEGIN SELECT RAISE(ABORT, 'report revision link already exists'); END;

CREATE TRIGGER report_claim_revision_links_sealed BEFORE INSERT ON report_claim_revision_links
WHEN (SELECT link_count FROM report_claim_revisions WHERE id = NEW.revision_id) IS NULL
  OR (SELECT COUNT(*) FROM report_claim_revision_links WHERE revision_id = NEW.revision_id)
     >= (SELECT link_count FROM report_claim_revisions WHERE id = NEW.revision_id)
  OR (SELECT claim_id FROM report_citation_links WHERE id = NEW.link_id)
     IS NOT (SELECT claim_id FROM report_claim_revisions WHERE id = NEW.revision_id)
BEGIN SELECT RAISE(ABORT, 'report revision citation set is sealed or belongs to another claim'); END;

CREATE TRIGGER report_claim_revision_links_no_update BEFORE UPDATE ON report_claim_revision_links
BEGIN SELECT RAISE(ABORT, 'report revision links are immutable'); END;

CREATE TRIGGER report_claim_revision_links_no_delete BEFORE DELETE ON report_claim_revision_links
WHEN NOT EXISTS (SELECT 1 FROM report_claim_revisions v JOIN report_claims c ON c.id = v.claim_id
                 JOIN report_sections s ON s.id = c.report_section_id JOIN reports r ON r.id = s.report_id
                 JOIN research_purge_authorizations a ON a.research_id = r.research_id
                 WHERE v.id = OLD.revision_id)
BEGIN SELECT RAISE(ABORT, 'report revision links are immutable'); END;

CREATE TRIGGER owner_reviews_snapshot_guard BEFORE INSERT ON owner_reviews
WHEN NOT EXISTS (SELECT 1 FROM owner_review_snapshots WHERE id = NEW.snapshot_id AND research_id = NEW.research_id)
BEGIN SELECT RAISE(ABORT, 'owner review snapshot belongs to another research'); END;

CREATE TRIGGER owner_review_findings_step_guard BEFORE INSERT ON owner_review_findings
WHEN NOT EXISTS (SELECT 1 FROM step_inputs i JOIN owner_reviews r ON r.run_id = i.run_id
                 WHERE r.id = NEW.review_id AND i.id = NEW.step_input_id AND i.research_id = r.research_id)
BEGIN SELECT RAISE(ABORT, 'finding step input belongs to another run'); END;

CREATE TRIGGER owner_review_snapshots_no_conflicting_insert BEFORE INSERT ON owner_review_snapshots
WHEN EXISTS (SELECT 1 FROM owner_review_snapshots WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'owner_review_snapshots already exists'); END;

CREATE TRIGGER owner_review_snapshots_no_delete BEFORE DELETE ON owner_review_snapshots
WHEN NOT EXISTS (SELECT 1 FROM research_purge_authorizations WHERE research_id = OLD.research_id)
BEGIN SELECT RAISE(ABORT, 'owner_review_snapshots requires research purge authorization'); END;

CREATE TRIGGER owner_review_snapshots_no_update BEFORE UPDATE ON owner_review_snapshots
BEGIN SELECT RAISE(ABORT, 'owner_review_snapshots is immutable'); END;

CREATE TRIGGER owner_reviews_no_conflicting_insert BEFORE INSERT ON owner_reviews
WHEN EXISTS (SELECT 1 FROM owner_reviews WHERE id = NEW.id OR run_id = NEW.run_id OR idempotency_key = NEW.idempotency_key)
BEGIN SELECT RAISE(ABORT, 'owner_reviews already exists'); END;

CREATE TRIGGER owner_reviews_no_delete BEFORE DELETE ON owner_reviews
WHEN NOT EXISTS (SELECT 1 FROM research_purge_authorizations WHERE research_id = OLD.research_id)
BEGIN SELECT RAISE(ABORT, 'owner_reviews requires research purge authorization'); END;

CREATE TRIGGER owner_reviews_frozen_columns BEFORE UPDATE ON owner_reviews
WHEN NEW.id IS NOT OLD.id OR NEW.research_id IS NOT OLD.research_id OR NEW.snapshot_id IS NOT OLD.snapshot_id OR NEW.run_id IS NOT OLD.run_id OR NEW.focus IS NOT OLD.focus OR NEW.owner_note IS NOT OLD.owner_note OR NEW.requested_connection IS NOT OLD.requested_connection OR NEW.requested_model IS NOT OLD.requested_model OR NEW.requested_effort IS NOT OLD.requested_effort OR NEW.idempotency_key IS NOT OLD.idempotency_key OR NEW.created_at IS NOT OLD.created_at
BEGIN SELECT RAISE(ABORT, 'owner_reviews frozen columns are immutable'); END;

CREATE TRIGGER owner_review_findings_no_conflicting_insert BEFORE INSERT ON owner_review_findings
WHEN EXISTS (SELECT 1 FROM owner_review_findings WHERE id = NEW.id OR (review_id = NEW.review_id AND ordinal = NEW.ordinal))
BEGIN SELECT RAISE(ABORT, 'owner_review_findings already exists'); END;

CREATE TRIGGER owner_review_findings_no_delete BEFORE DELETE ON owner_review_findings
WHEN NOT EXISTS (SELECT 1 FROM owner_reviews r JOIN research_purge_authorizations a ON a.research_id = r.research_id WHERE r.id = OLD.review_id)
BEGIN SELECT RAISE(ABORT, 'owner_review_findings requires research purge authorization'); END;

CREATE TRIGGER owner_review_findings_no_update BEFORE UPDATE ON owner_review_findings
BEGIN SELECT RAISE(ABORT, 'owner_review_findings is immutable'); END;

CREATE TRIGGER owner_review_decisions_no_delete BEFORE DELETE ON owner_review_decisions
WHEN NOT EXISTS (SELECT 1 FROM owner_review_findings f JOIN owner_reviews r ON r.id = f.review_id JOIN research_purge_authorizations a ON a.research_id = r.research_id WHERE f.id = OLD.finding_id)
BEGIN SELECT RAISE(ABORT, 'owner_review_decisions requires research purge authorization'); END;

CREATE TRIGGER owner_review_decisions_no_update BEFORE UPDATE ON owner_review_decisions
BEGIN SELECT RAISE(ABORT, 'owner_review_decisions is immutable'); END;

CREATE TRIGGER owner_review_decisions_no_conflicting_insert BEFORE INSERT ON owner_review_decisions
WHEN EXISTS (SELECT 1 FROM owner_review_decisions WHERE id = NEW.id
 OR (finding_id = NEW.finding_id AND ordinal = NEW.ordinal)
 OR idempotency_key = NEW.idempotency_key)
BEGIN SELECT RAISE(ABORT, 'owner_review_decisions already exists'); END;

CREATE TRIGGER asset_file_observations_no_update BEFORE UPDATE ON asset_file_observations
BEGIN SELECT RAISE(ABORT, 'file observations are immutable'); END;

CREATE TRIGGER asset_file_observations_no_conflicting_insert BEFORE INSERT ON asset_file_observations
WHEN EXISTS (SELECT 1 FROM asset_file_observations WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'file observations are immutable'); END;

CREATE TRIGGER asset_extractions_no_update BEFORE UPDATE ON asset_extractions
WHEN NEW.id IS NOT OLD.id
  OR NEW.asset_id IS NOT OLD.asset_id
  OR NEW.extraction_version IS NOT OLD.extraction_version
  OR NEW.status IS NOT OLD.status
  OR NEW.error IS NOT OLD.error
  OR NEW.page_count IS NOT OLD.page_count
  OR NEW.text_pages IS NOT OLD.text_pages
  OR NEW.passage_count IS NOT OLD.passage_count
  OR NEW.rejection_reason IS NOT OLD.rejection_reason
  OR NEW.created_at IS NOT OLD.created_at
  OR NEW.math_json IS NOT OLD.math_json
  OR NEW.ocr_json IS NOT OLD.ocr_json
  OR NEW.extractor_profile IS NOT OLD.extractor_profile
  OR NEW.recovery_operation_id IS NOT OLD.recovery_operation_id
  OR NEW.baseline_extraction_id IS NOT OLD.baseline_extraction_id
  OR NEW.input_observation_id IS NOT OLD.input_observation_id
  OR NEW.diagnostic_only IS NOT OLD.diagnostic_only
  OR NEW.decision_code IS NOT OLD.decision_code
  OR (NEW.outcome IS NOT OLD.outcome AND NOT (
    (OLD.outcome = 'current' AND NEW.outcome = 'superseded') OR
    (OLD.outcome = 'superseded' AND NEW.outcome = 'current')))
BEGIN SELECT RAISE(ABORT, 'extraction content is immutable'); END;

CREATE TRIGGER asset_extractions_baseline_same_asset BEFORE INSERT ON asset_extractions
WHEN NEW.baseline_extraction_id IS NOT NULL AND NOT EXISTS (
  SELECT 1 FROM asset_extractions WHERE id = NEW.baseline_extraction_id AND asset_id = NEW.asset_id)
BEGIN SELECT RAISE(ABORT, 'extraction baseline belongs to another asset'); END;

CREATE TRIGGER asset_extractions_recovery_shape BEFORE INSERT ON asset_extractions
WHEN (NEW.recovery_operation_id IS NOT NULL AND (
    NOT EXISTS (SELECT 1 FROM asset_recovery_operations WHERE id = NEW.recovery_operation_id
      AND kind = 'text_retry' AND asset_id = NEW.asset_id)
    OR NEW.extraction_version IS NOT (NEW.extractor_profile || '+reextract-' || NEW.recovery_operation_id)))
  OR (instr(NEW.extraction_version, '+reextract-') = 0 AND NEW.extractor_profile IS NOT NEW.extraction_version)
  OR (NEW.extractor_profile = 'unknown' AND NEW.extraction_version <> 'unknown')
BEGIN SELECT RAISE(ABORT, 'invalid extraction occurrence profile'); END;

CREATE TRIGGER asset_extractions_no_conflicting_insert BEFORE INSERT ON asset_extractions
WHEN EXISTS (SELECT 1 FROM asset_extractions WHERE id = NEW.id OR rowid = NEW.rowid
  OR (asset_id = NEW.asset_id AND extraction_version = NEW.extraction_version)
  OR (asset_id = NEW.asset_id AND outcome = 'current' AND NEW.outcome = 'current')
  OR (NEW.recovery_operation_id IS NOT NULL AND recovery_operation_id = NEW.recovery_operation_id))
BEGIN SELECT RAISE(ABORT, 'extraction occurrence already exists'); END;

CREATE TRIGGER asset_recovery_operations_no_conflicting_insert BEFORE INSERT ON asset_recovery_operations
WHEN EXISTS (SELECT 1 FROM asset_recovery_operations WHERE id = NEW.id OR idempotency_key = NEW.idempotency_key
  OR (NEW.kind = 'text_retry' AND NEW.lifecycle = 'running' AND kind = 'text_retry'
    AND lifecycle = 'running' AND asset_id = NEW.asset_id))
BEGIN SELECT RAISE(ABORT, 'recovery operation already exists'); END;

CREATE TRIGGER asset_recovery_operations_frozen BEFORE UPDATE ON asset_recovery_operations
WHEN OLD.lifecycle <> 'running'
  OR NEW.id IS NOT OLD.id
  OR NEW.kind IS NOT OLD.kind
  OR NEW.asset_id IS NOT OLD.asset_id
  OR NEW.research_id IS NOT OLD.research_id
  OR NEW.expected_sha256 IS NOT OLD.expected_sha256
  OR NEW.expected_byte_size IS NOT OLD.expected_byte_size
  OR NEW.baseline_extraction_id IS NOT OLD.baseline_extraction_id
  OR NEW.baseline_profile IS NOT OLD.baseline_profile
  OR NEW.mode IS NOT OLD.mode
  OR NEW.idempotency_key IS NOT OLD.idempotency_key
  OR NEW.request_fingerprint IS NOT OLD.request_fingerprint
  OR NEW.created_at IS NOT OLD.created_at
  OR (NEW.lifecycle IS NOT OLD.lifecycle AND NEW.lifecycle NOT IN ('completed', 'interrupted'))
  OR (NEW.before_observation_id IS NOT OLD.before_observation_id AND NOT (
    OLD.kind = 'file_restore' AND OLD.before_observation_id IS NULL AND NEW.before_observation_id IS NOT NULL
    AND EXISTS (SELECT 1 FROM asset_file_observations WHERE id = NEW.before_observation_id
      AND operation_id = OLD.id AND kind = 'before_restore')))
  OR (NEW.after_observation_id IS NOT OLD.after_observation_id AND NOT (
    OLD.kind = 'file_restore' AND OLD.after_observation_id IS NULL AND NEW.after_observation_id IS NOT NULL
    AND EXISTS (SELECT 1 FROM asset_file_observations WHERE id = NEW.after_observation_id
      AND operation_id = OLD.id AND kind = 'after_restore')))
BEGIN SELECT RAISE(ABORT, 'recovery operation is frozen'); END;

CREATE TRIGGER passages_no_update BEFORE UPDATE OF text, source_version_id, kind, physical_page, asset_id,
  printed_label, abstract_origin, payload_ref, extraction_version, text_sha256, text_source, retrieved_at, created_at ON passages
BEGIN SELECT RAISE(ABORT, 'passage content is immutable; create a new passage'); END;

CREATE TRIGGER watch_reads_parent_guard BEFORE INSERT ON watch_reads
WHEN NOT EXISTS (SELECT 1 FROM watch_checks c JOIN run_steps s ON s.run_id=c.run_id
 WHERE c.id=NEW.check_id AND c.research_id=NEW.research_id AND s.id=NEW.step_id)
BEGIN SELECT RAISE(ABORT,'watch read requires its check step'); END;

CREATE TRIGGER watch_checks_no_conflicting_insert BEFORE INSERT ON watch_checks
WHEN EXISTS (SELECT 1 FROM watch_checks WHERE id=NEW.id OR run_id=NEW.run_id OR request_key=NEW.request_key
 OR (watch_id=NEW.watch_id AND period_start=NEW.period_start))
BEGIN SELECT RAISE(ABORT,'watch_checks already exists'); END;

CREATE TRIGGER watch_reads_no_conflicting_insert BEFORE INSERT ON watch_reads
WHEN EXISTS (SELECT 1 FROM watch_reads WHERE id=NEW.id OR step_id=NEW.step_id
 OR (check_id=NEW.check_id AND unit_key=NEW.unit_key AND page_number=NEW.page_number))
BEGIN SELECT RAISE(ABORT,'watch_reads already exists'); END;

CREATE TRIGGER watch_checks_no_update BEFORE UPDATE ON watch_checks
WHEN NEW.id IS NOT OLD.id OR NEW.watch_id IS NOT OLD.watch_id OR NEW.research_id IS NOT OLD.research_id
 OR NEW.run_id IS NOT OLD.run_id OR NEW.trigger IS NOT OLD.trigger OR NEW.period_start IS NOT OLD.period_start
 OR NEW.requested_from IS NOT OLD.requested_from OR NEW.requested_to IS NOT OLD.requested_to
 OR NEW.config_json IS NOT OLD.config_json OR NEW.state_version IS NOT OLD.state_version
 OR NEW.missed_periods IS NOT OLD.missed_periods OR NEW.request_key IS NOT OLD.request_key
 OR NEW.request_hash IS NOT OLD.request_hash OR NEW.created_at IS NOT OLD.created_at
 OR (NEW.observed_json IS NOT OLD.observed_json AND OLD.observed_json IS NOT NULL)
 OR (NEW.provider_status_json IS NOT OLD.provider_status_json AND OLD.provider_status_json IS NOT NULL)
 OR (NEW.counts_json IS NOT OLD.counts_json AND OLD.counts_json IS NOT NULL)
 OR (NEW.completed_at IS NOT OLD.completed_at AND OLD.completed_at IS NOT NULL)
BEGIN SELECT RAISE(ABORT,'watch_checks frozen columns are immutable'); END;

CREATE TRIGGER watch_reads_no_update BEFORE UPDATE ON watch_reads
BEGIN SELECT RAISE(ABORT,'watch_reads is immutable'); END;

CREATE TRIGGER watch_checks_no_delete BEFORE DELETE ON watch_checks
WHEN NOT EXISTS (SELECT 1 FROM research_purge_authorizations WHERE research_id=OLD.research_id)
BEGIN SELECT RAISE(ABORT,'watch_checks requires research purge authorization'); END;

CREATE TRIGGER watch_reads_no_delete BEFORE DELETE ON watch_reads
WHEN NOT EXISTS (SELECT 1 FROM research_purge_authorizations WHERE research_id=OLD.research_id)
BEGIN SELECT RAISE(ABORT,'watch_reads requires research purge authorization'); END;

CREATE TRIGGER asset_recovery_operations_delete_guard BEFORE DELETE ON asset_recovery_operations
WHEN NOT EXISTS (SELECT 1 FROM recovery_purge_authorizations WHERE sha256 = OLD.expected_sha256)
BEGIN SELECT RAISE(ABORT, 'recovery history requires purge authorization'); END;

CREATE TRIGGER asset_file_observations_delete_guard BEFORE DELETE ON asset_file_observations
WHEN NOT EXISTS (SELECT 1 FROM recovery_purge_authorizations WHERE sha256 = OLD.expected_sha256)
BEGIN SELECT RAISE(ABORT, 'recovery history requires purge authorization'); END;

CREATE TRIGGER watches_schedule_insert BEFORE INSERT ON watches
WHEN (NEW.mode='manual' AND (NEW.interval_days IS NOT NULL OR NEW.catch_up IS NOT NULL OR NEW.next_due_at IS NOT NULL))
 OR (NEW.mode='interval' AND (NEW.interval_days IS NULL OR NEW.catch_up IS NULL OR (NEW.enabled=1 AND NEW.next_due_at IS NULL)))
BEGIN SELECT RAISE(ABORT,'incoherent watch schedule'); END;

CREATE TRIGGER watches_schedule_update BEFORE UPDATE ON watches
WHEN (NEW.mode='manual' AND (NEW.interval_days IS NOT NULL OR NEW.catch_up IS NOT NULL OR NEW.next_due_at IS NOT NULL))
 OR (NEW.mode='interval' AND (NEW.interval_days IS NULL OR NEW.catch_up IS NULL OR (NEW.enabled=1 AND NEW.next_due_at IS NULL)))
BEGIN SELECT RAISE(ABORT,'incoherent watch schedule'); END;

CREATE TRIGGER watch_schedule_changes_parent_guard BEFORE INSERT ON watch_schedule_changes
WHEN NOT EXISTS (SELECT 1 FROM watches WHERE id=NEW.watch_id AND research_id=NEW.research_id)
BEGIN SELECT RAISE(ABORT,'schedule change requires its research watch'); END;

CREATE TRIGGER watch_gaps_parent_guard BEFORE INSERT ON watch_gaps
WHEN NOT EXISTS (SELECT 1 FROM watches WHERE id=NEW.watch_id AND research_id=NEW.research_id)
BEGIN SELECT RAISE(ABORT,'gap requires its research watch'); END;

CREATE TRIGGER watch_schedule_changes_no_conflicting_insert BEFORE INSERT ON watch_schedule_changes
WHEN EXISTS (SELECT 1 FROM watch_schedule_changes WHERE id=NEW.id OR request_key=NEW.request_key
 OR (watch_id=NEW.watch_id AND schedule_version=NEW.schedule_version))
BEGIN SELECT RAISE(ABORT,'watch_schedule_changes already exists'); END;

CREATE TRIGGER watch_gaps_no_conflicting_insert BEFORE INSERT ON watch_gaps
WHEN EXISTS (SELECT 1 FROM watch_gaps WHERE id=NEW.id OR (watch_id=NEW.watch_id AND opening_id=NEW.opening_id))
BEGIN SELECT RAISE(ABORT,'watch_gaps already exists'); END;

CREATE TRIGGER watch_schedule_changes_no_update BEFORE UPDATE ON watch_schedule_changes
BEGIN SELECT RAISE(ABORT,'watch_schedule_changes is immutable'); END;

CREATE TRIGGER watch_gaps_no_update BEFORE UPDATE ON watch_gaps
BEGIN SELECT RAISE(ABORT,'watch_gaps is immutable'); END;

CREATE TRIGGER watch_schedule_changes_no_delete BEFORE DELETE ON watch_schedule_changes
WHEN NOT EXISTS (SELECT 1 FROM research_purge_authorizations WHERE research_id=OLD.research_id)
BEGIN SELECT RAISE(ABORT,'watch_schedule_changes requires research purge authorization'); END;

CREATE TRIGGER watch_gaps_no_delete BEFORE DELETE ON watch_gaps
WHEN NOT EXISTS (SELECT 1 FROM research_purge_authorizations WHERE research_id=OLD.research_id)
BEGIN SELECT RAISE(ABORT,'watch_gaps requires research purge authorization'); END;

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
