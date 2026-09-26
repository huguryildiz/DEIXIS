-- deixis:foreign-keys-off
-- Slice 22 (D104): equations from the authors' arXiv LaTeX source.
-- 1. passages.text_source gains 'latex_source': a chunk of the PDF's own text in which one or more displayed equations
--    numbered on the page were replaced by the authors' LaTeX. SQLite cannot widen a CHECK in place, so the table is
--    rebuilt from 0053's own DDL with only that CHECK changed; every column and rowid is copied (passages_fts is an
--    external-content FTS5 table keyed by rowid and is not touched). The one trigger elsewhere that names passages,
--    cell_evidence_same_source, is dropped before the rename and written back verbatim after it.
-- 2. arxiv_sources: one row per arXiv version whose source was requested (download status and archive content apart).
-- 3. asset_arxiv_versions: a PDF's own arXiv version and whether its record may take that version's source.
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
  created_at TEXT NOT NULL, text_source TEXT NOT NULL DEFAULT 'text_layer' CHECK (text_source IN ('text_layer', 'ocr', 'marker', 'latex_source')),
  CHECK (kind <> 'abstract' OR (physical_page IS NULL AND abstract_origin IS NOT NULL)),
  CHECK (kind <> 'pdf_page' OR (physical_page IS NOT NULL AND asset_id IS NOT NULL))
);
INSERT INTO passages_new (rowid, id, source_version_id, asset_id, kind, physical_page, printed_label, abstract_origin, payload_ref,
  extraction_version, text, text_sha256, retrieved_at, created_at, text_source)
  SELECT rowid, id, source_version_id, asset_id, kind, physical_page, printed_label, abstract_origin, payload_ref,
  extraction_version, text, text_sha256, retrieved_at, created_at, text_source FROM passages;
DROP TRIGGER cell_evidence_same_source;
DROP TABLE passages;
ALTER TABLE passages_new RENAME TO passages;
CREATE INDEX passages_source ON passages(source_version_id);
CREATE TRIGGER passages_fts_insert AFTER INSERT ON passages
BEGIN INSERT INTO passages_fts(rowid, text) VALUES (new.rowid, new.text); END;
CREATE TRIGGER passages_no_update BEFORE UPDATE OF text, source_version_id, kind, physical_page ON passages
BEGIN SELECT RAISE(ABORT, 'passage content is immutable; create a new passage'); END;
CREATE TRIGGER cell_evidence_same_source BEFORE INSERT ON cell_evidence_links
WHEN NEW.source_version_id IS NOT (SELECT c.source_version_id FROM cell_revisions r JOIN evidence_cells c ON c.id = r.cell_id WHERE r.id = NEW.cell_revision_id)
  OR NEW.source_version_id IS NOT (SELECT source_version_id FROM passages WHERE id = NEW.passage_id)
BEGIN SELECT RAISE(ABORT, 'cell evidence must come from the cell source version'); END;

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
