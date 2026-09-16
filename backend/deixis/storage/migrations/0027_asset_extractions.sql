-- D45: a source version has at most one PDF in use, a removal records why, and every text extraction of a file is recorded.
-- A new extraction or a replacing file adds passages; the old ones stay resolvable for the evidence that cites them.
ALTER TABLE source_assets ADD COLUMN removal_reason TEXT CHECK (removal_reason IN ('wrong_file', 'replaced'));
ALTER TABLE source_assets ADD COLUMN replaced_by_asset_id TEXT REFERENCES source_assets(id);

-- Fails, and leaves the library unchanged, if a source version already has two PDFs in use; no file is withdrawn by code.
CREATE UNIQUE INDEX source_assets_one_in_use ON source_assets(source_version_id) WHERE removed_at IS NULL;

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
  created_at TEXT NOT NULL,
  UNIQUE (asset_id, extraction_version)
);
-- source_assets.extraction_version, extraction_status and page_count mirror the current extraction.
CREATE UNIQUE INDEX asset_extractions_one_current ON asset_extractions(asset_id) WHERE outcome = 'current';

INSERT INTO asset_extractions (id, asset_id, extraction_version, status, error, page_count, text_pages, passage_count, outcome, created_at)
SELECT 'ext_' || a.id, a.id, IFNULL(a.extraction_version, 'unknown'), a.extraction_status, a.extraction_error, a.page_count,
       (SELECT COUNT(DISTINCT p.physical_page) FROM passages p WHERE p.asset_id = a.id AND p.extraction_version IS a.extraction_version),
       (SELECT COUNT(*) FROM passages p WHERE p.asset_id = a.id AND p.extraction_version IS a.extraction_version),
       'current', a.retrieved_at
FROM source_assets a;
