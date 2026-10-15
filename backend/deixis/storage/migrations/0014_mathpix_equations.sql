-- deixis:foreign-keys-off
-- Mathpix equation reading (D40). `passages.text_source` gains `equation_ocr`: a chunk holding a numbered display
-- equation read by Mathpix from an image of the page. SQLite cannot change a CHECK in place, so `passages` is rebuilt
-- (SQLite's 12-step procedure, as 0007 did for `runs`): every row is copied with its rowid, so the external-content FTS
-- index and every reference stay valid; the triggers that read `passages` are dropped and recreated with the same text,
-- and its indexes, its FTS insert trigger and its immutability trigger are recreated.
CREATE TABLE passages_new (
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
  created_at TEXT NOT NULL, text_source TEXT NOT NULL DEFAULT 'text_layer' CHECK (text_source IN ('text_layer', 'ocr', 'marker', 'latex_source', 'equation_ocr')),
  CHECK (kind <> 'abstract' OR (physical_page IS NULL AND abstract_origin IS NOT NULL)),
  CHECK (kind <> 'pdf_page' OR (physical_page IS NOT NULL AND asset_id IS NOT NULL))
);
INSERT INTO passages_new (rowid, id, source_version_id, asset_id, kind, physical_page, printed_label, abstract_origin, payload_ref,
  extraction_version, text, text_sha256, retrieved_at, created_at, text_source)
  SELECT rowid, id, source_version_id, asset_id, kind, physical_page, printed_label, abstract_origin, payload_ref,
  extraction_version, text, text_sha256, retrieved_at, created_at, text_source FROM passages;
DROP TRIGGER cell_evidence_same_source;
DROP TRIGGER lineage_link_evidence_same_source;
DROP TRIGGER claim_matrix_evidence_integrity;
DROP TABLE passages;
ALTER TABLE passages_new RENAME TO passages;
CREATE INDEX passages_source ON passages(source_version_id);
CREATE INDEX passages_asset ON passages(asset_id, kind);
CREATE TRIGGER passages_fts_insert AFTER INSERT ON passages
BEGIN INSERT INTO passages_fts(rowid, text) VALUES (new.rowid, new.text); END;
CREATE TRIGGER passages_no_update BEFORE UPDATE OF text, source_version_id, kind, physical_page, asset_id,
  printed_label, abstract_origin, payload_ref, extraction_version, text_sha256, text_source, retrieved_at, created_at ON passages
BEGIN SELECT RAISE(ABORT, 'passage content is immutable; create a new passage'); END;
CREATE TRIGGER cell_evidence_same_source BEFORE INSERT ON cell_evidence_links
WHEN NEW.source_version_id IS NOT (SELECT c.source_version_id FROM cell_revisions r JOIN evidence_cells c ON c.id = r.cell_id WHERE r.id = NEW.cell_revision_id)
  OR NEW.source_version_id IS NOT (SELECT source_version_id FROM passages WHERE id = NEW.passage_id)
BEGIN SELECT RAISE(ABORT, 'cell evidence must come from the cell source version'); END;
CREATE TRIGGER lineage_link_evidence_same_source BEFORE INSERT ON lineage_link_evidence
WHEN NEW.source_version_id IS NOT (SELECT source_version_id FROM passages WHERE id = NEW.passage_id)
  OR NEW.source_version_id IS NOT (SELECT l.to_source_version_id FROM lineage_link_revisions r
                                   JOIN lineage_links l ON l.id = r.link_id WHERE r.id = NEW.link_revision_id)
BEGIN SELECT RAISE(ABORT, 'lineage evidence must come from the later work'); END;
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
-- One row per request DEIXIS reserved or sent to Mathpix, kept across extraction retries: an `answered` row with the
-- same crop hash is reused instead of a new request, and the rows count against the monthly and per-PDF budgets.
-- `unknown`: a timeout or a connection lost after sending (Mathpix may have processed it). `credential_revision` is the
-- key pair's revision the request was sent with; a 401/403 marks the pair refused only while that revision is saved.
CREATE TABLE mathpix_requests (
  id TEXT PRIMARY KEY,
  crop_sha256 TEXT NOT NULL,
  asset_id TEXT NOT NULL,
  file_sha256 TEXT NOT NULL,
  page INTEGER NOT NULL,
  n TEXT NOT NULL,
  attempt INTEGER NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('reserved', 'answered', 'error', 'unknown')),
  http_status INTEGER,
  request_id TEXT,
  response_json TEXT,
  reason TEXT,
  credential_revision TEXT NOT NULL,
  reserved_at TEXT NOT NULL,
  answered_at TEXT
);
CREATE INDEX mathpix_requests_crop ON mathpix_requests(crop_sha256, status);
CREATE INDEX mathpix_requests_asset ON mathpix_requests(asset_id);
CREATE INDEX mathpix_requests_month ON mathpix_requests(reserved_at);
