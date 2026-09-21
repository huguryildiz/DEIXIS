-- The works a record's own bibliography lists, in OpenAlex's short work identifiers (SW7). Library-wide as the
-- reference count is (SW5.1): a bibliography belongs to the record, not to the research that read it.
CREATE TABLE record_references (
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  referenced_id TEXT NOT NULL,          -- OpenAlex work id, short form (W…)
  PRIMARY KEY (source_version_id, referenced_id)
) WITHOUT ROWID;
-- Whether a read has asked OpenAlex for this record's list at all. A record read with an empty list has no graph
-- signal, exactly as an unread one has none, but the two are not the same state and are not stored as one.
ALTER TABLE source_versions ADD COLUMN references_read INTEGER NOT NULL DEFAULT 0;
