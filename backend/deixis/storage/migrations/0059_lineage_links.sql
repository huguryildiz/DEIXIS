-- deixis:foreign-keys-off
-- Lineage runs carry {"table_id", "plan_version", ...}; L5 defines the remaining target fields.
-- Rebuild runs as in 0046, retaining every column and dependent row.
CREATE TABLE runs_new (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  scope_revision INTEGER NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('discovery', 'answer', 'table_columns', 'table_fill', 'cell_recheck', 'research_title', 'pdf_collection', 'pdf_ocr', 'report', 'fulltext_fetch', 'fulltext_adjudication', 'lineage_links')),
  status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'pause_requested', 'paused', 'completed', 'failed', 'cancelled')),
  stage TEXT NOT NULL CHECK (stage IN ('intake', 'discovery', 'screening', 'inspection', 'answer', 'extraction', 'synthesis', 'candidate', 'claim_check', 'export')),
  pause_reason TEXT,
  error_json TEXT,
  budget_json TEXT NOT NULL,
  usage_json TEXT NOT NULL DEFAULT '{}',
  idempotency_key TEXT UNIQUE,
  -- Table runs: {"table_id", "column_ids", "cell_id", "include_stale"}. Report runs: {"report_id"}.
  -- Lineage runs: {"table_id", "plan_version", ...}. NULL otherwise.
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

-- A pair holds decisions, including negative decisions and human removal. The pointer names a decision record,
-- not necessarily an active link; only an accepted current decision='link' is an active link.
-- Explicit primary keys are the only row identities; hidden rowid collisions must not bypass insert guards.
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
CREATE INDEX lineage_link_revisions_link ON lineage_link_revisions(link_id, created_at);
CREATE TABLE lineage_link_evidence (
  link_revision_id TEXT NOT NULL REFERENCES lineage_link_revisions(id),
  passage_id TEXT NOT NULL REFERENCES passages(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  anchor_text TEXT NOT NULL,
  anchor_match TEXT NOT NULL CHECK (anchor_match IN ('exact', 'normalized', 'fuzzy')),
  PRIMARY KEY (link_revision_id, passage_id, anchor_text)
) WITHOUT ROWID;
-- REPLACE can delete conflicts without delete triggers when recursive_triggers is off.
-- Reject every unique-key collision before SQLite applies any conflict clause.
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
