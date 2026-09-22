-- Scopus answers the abstract lookup of an sw run as its last source, on an institutional network only (D91).
-- SQLite cannot change a CHECK constraint in place, so the table is rebuilt with its rows; nothing references it.
CREATE TABLE record_lookups_new (
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  provider TEXT NOT NULL CHECK (provider IN ('semantic_scholar', 'crossref', 'scopus')),
  status TEXT NOT NULL CHECK (status IN ('found', 'not_found', 'failed')),
  had_abstract INTEGER NOT NULL CHECK (had_abstract IN (0, 1)),
  step_id TEXT,
  asked_at TEXT NOT NULL,
  PRIMARY KEY (source_version_id, provider)
);
INSERT INTO record_lookups_new (source_version_id, provider, status, had_abstract, step_id, asked_at)
  SELECT source_version_id, provider, status, had_abstract, step_id, asked_at FROM record_lookups;
DROP TABLE record_lookups;
ALTER TABLE record_lookups_new RENAME TO record_lookups;
