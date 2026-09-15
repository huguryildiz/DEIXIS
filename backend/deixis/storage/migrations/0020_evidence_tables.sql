-- Evidence tables (P5, D37). A table belongs to one research; its rows are that research's source versions, listed
-- explicitly; its columns are revisioned field definitions. A cell is an append-only list of revisions, and the cell
-- points at the revision it currently shows. Revisions, their evidence links and column revisions are immutable;
-- permanent deletion of a research is the only exception, as for step inputs (0010).

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
CREATE INDEX evidence_tables_research ON evidence_tables(research_id, created_at);

-- A row is a source version of the table's research. Removing a row keeps its cells; adding it again clears removed_at.
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
);

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

-- kind: model_fill (model value for an empty cell), model_proposal (waits for the user), system_fill (no text to read),
-- human_edit, accept_proposal (the proposal's value and evidence, chosen by the user), dismiss_proposal.
-- state 'not_verified': a value recorded without linked evidence. It and 'value' carry value_json; no other state does.
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
CREATE INDEX cell_revisions_cell ON cell_revisions(cell_id, created_at);

CREATE TABLE cell_evidence_links (
  cell_revision_id TEXT NOT NULL REFERENCES cell_revisions(id),
  passage_id TEXT NOT NULL REFERENCES passages(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  step_input_id TEXT REFERENCES step_inputs(id),  -- the StepInput that gave the passage; kept when a proposal is accepted
  anchor_text TEXT,
  anchor_match TEXT CHECK (anchor_match IN ('exact', 'normalized', 'fuzzy')),
  PRIMARY KEY (cell_revision_id, passage_id)
);

-- Evidence comes from the cell's own source version, never from another version of the same work.
CREATE TRIGGER cell_evidence_same_source BEFORE INSERT ON cell_evidence_links
WHEN NEW.source_version_id IS NOT (SELECT c.source_version_id FROM cell_revisions r JOIN evidence_cells c ON c.id = r.cell_id WHERE r.id = NEW.cell_revision_id)
  OR NEW.source_version_id IS NOT (SELECT source_version_id FROM passages WHERE id = NEW.passage_id)
BEGIN SELECT RAISE(ABORT, 'cell evidence must come from the cell source version'); END;

CREATE TRIGGER column_revisions_no_update BEFORE UPDATE ON column_revisions
BEGIN SELECT RAISE(ABORT, 'column revisions are immutable'); END;
CREATE TRIGGER column_revisions_no_delete BEFORE DELETE ON column_revisions
WHEN NOT EXISTS (SELECT 1 FROM table_columns c JOIN evidence_tables t ON t.id = c.table_id
                 JOIN research_purge_authorizations a ON a.research_id = t.research_id WHERE c.id = OLD.column_id)
BEGIN SELECT RAISE(ABORT, 'column revisions are immutable'); END;

CREATE TRIGGER cell_revisions_no_update BEFORE UPDATE ON cell_revisions
BEGIN SELECT RAISE(ABORT, 'cell revisions are immutable'); END;
CREATE TRIGGER cell_revisions_no_delete BEFORE DELETE ON cell_revisions
WHEN NOT EXISTS (SELECT 1 FROM evidence_cells c JOIN evidence_tables t ON t.id = c.table_id
                 JOIN research_purge_authorizations a ON a.research_id = t.research_id WHERE c.id = OLD.cell_id)
BEGIN SELECT RAISE(ABORT, 'cell revisions are immutable'); END;

CREATE TRIGGER cell_evidence_links_no_update BEFORE UPDATE ON cell_evidence_links
BEGIN SELECT RAISE(ABORT, 'cell evidence links are immutable'); END;
CREATE TRIGGER cell_evidence_links_no_delete BEFORE DELETE ON cell_evidence_links
WHEN NOT EXISTS (SELECT 1 FROM cell_revisions r JOIN evidence_cells c ON c.id = r.cell_id JOIN evidence_tables t ON t.id = c.table_id
                 JOIN research_purge_authorizations a ON a.research_id = t.research_id WHERE r.id = OLD.cell_revision_id)
BEGIN SELECT RAISE(ABORT, 'cell evidence links are immutable'); END;
