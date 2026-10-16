-- deixis:foreign-keys-off
-- A table made from the included sources follows them (D63): `evidence_tables.follows_included` says so, and a row the
-- app adds for a source included after the table was made is `added_by = 'included_later'`. SQLite cannot change a
-- CHECK in place, so `table_rows` is rebuilt (as 0004 rebuilt `runs`); every row is copied unchanged. No index, trigger
-- or foreign key refers to `table_rows`.
ALTER TABLE evidence_tables ADD COLUMN follows_included INTEGER NOT NULL DEFAULT 0;
-- A table that took its rows from the included sources has at least one such row; one made from "included" while
-- nothing was included has none and stays 0.
UPDATE evidence_tables SET follows_included = 1
WHERE EXISTS (SELECT 1 FROM table_rows t WHERE t.table_id = evidence_tables.id AND t.added_by = 'included_at_creation');
CREATE TABLE table_rows_new (
  table_id TEXT NOT NULL REFERENCES evidence_tables(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  added_by TEXT NOT NULL CHECK (added_by IN ('included_at_creation', 'user', 'included_later')),
  created_at TEXT NOT NULL,
  removed_at TEXT,
  PRIMARY KEY (table_id, source_version_id)
);
INSERT INTO table_rows_new SELECT table_id, source_version_id, added_by, created_at, removed_at FROM table_rows;
DROP TABLE table_rows;
ALTER TABLE table_rows_new RENAME TO table_rows;
