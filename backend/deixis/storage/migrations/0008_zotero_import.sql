-- Sources imported from a Zotero collection (D16) join a research with added_by 'zotero_import'.
-- SQLite cannot change a CHECK constraint in place, so the table is rebuilt; no table or trigger references it.
CREATE TABLE corpus_memberships_new (
  research_id TEXT NOT NULL REFERENCES researches(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  added_by TEXT NOT NULL CHECK (added_by IN ('search', 'user_upload', 'zotero_import')),
  created_at TEXT NOT NULL,
  PRIMARY KEY (research_id, source_version_id)
);
INSERT INTO corpus_memberships_new (research_id, source_version_id, added_by, created_at)
  SELECT research_id, source_version_id, added_by, created_at FROM corpus_memberships;
DROP TABLE corpus_memberships;
ALTER TABLE corpus_memberships_new RENAME TO corpus_memberships;
