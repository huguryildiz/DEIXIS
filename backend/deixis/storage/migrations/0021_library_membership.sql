-- A work the user drags from the Library into a research (D41) joins it with added_by 'library'.
-- SQLite cannot change a CHECK constraint in place, so the table is rebuilt; no table or trigger references it.
CREATE TABLE corpus_memberships_new (
  research_id TEXT NOT NULL REFERENCES researches(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  added_by TEXT NOT NULL CHECK (added_by IN ('search', 'user_upload', 'zotero_import', 'library')),
  created_at TEXT NOT NULL,
  PRIMARY KEY (research_id, source_version_id)
);
INSERT INTO corpus_memberships_new (research_id, source_version_id, added_by, created_at)
  SELECT research_id, source_version_id, added_by, created_at FROM corpus_memberships;
DROP TABLE corpus_memberships;
ALTER TABLE corpus_memberships_new RENAME TO corpus_memberships;
