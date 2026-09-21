-- deixis:foreign-keys-off
-- What a second source answered when it was asked about one record by DOI. Library-wide, as links are (D46): a
-- record is asked once per source, by whichever research asks first. A 'failed' row is asked again; the others are not.
CREATE TABLE record_lookups (
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  provider TEXT NOT NULL CHECK (provider IN ('semantic_scholar', 'crossref')),
  status TEXT NOT NULL CHECK (status IN ('found', 'not_found', 'failed')),
  had_abstract INTEGER NOT NULL CHECK (had_abstract IN (0, 1)),
  step_id TEXT,
  asked_at TEXT NOT NULL,
  PRIMARY KEY (source_version_id, provider)
);
-- A routing label code put on a record under one research's protocol (SW5.4). It removes nothing.
CREATE TABLE record_flags (
  research_id TEXT NOT NULL REFERENCES researches(id),
  scope_revision INTEGER NOT NULL,
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  flag TEXT NOT NULL,
  evidence TEXT NOT NULL,
  step_id TEXT,
  protocol_hash TEXT,
  created_at TEXT NOT NULL,
  PRIMARY KEY (research_id, scope_revision, source_version_id, flag)
);
-- How many works a record's own bibliography lists (SW5.1). A bibliography does not change, so this is not dated and
-- not overwritten as the citation count is; NULL means no source named it, never that the record cites nothing.
ALTER TABLE source_versions ADD COLUMN reference_count INTEGER;

-- SQLite cannot widen a CHECK in place, so record_links is rebuilt as selections was in 0038, to let an external
-- link (slice 05) name its source. Nothing references this table by foreign key, so only its own rows move.
CREATE TABLE record_links_new (
  id TEXT PRIMARY KEY,
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  other_source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  link_kind TEXT NOT NULL CHECK (link_kind IN ('same_work', 'extended_version', 'probable_version', 'related_suspected',
                                               'artifact_of', 'notice_of')),
  rule TEXT NOT NULL,
  source TEXT NOT NULL CHECK (source IN ('text', 'arxiv_doi', 'semantic_scholar', 'crossref_relation')),
  parent_source_version_id TEXT REFERENCES source_versions(id),
  title_similarity REAL,
  abstract_similarity REAL,
  author_agreement TEXT NOT NULL CHECK (author_agreement IN ('agree', 'differ', 'unknown')),
  year_gap INTEGER,
  merged INTEGER NOT NULL CHECK (merged IN (0, 1)),
  undo_json TEXT,
  closed_at TEXT,
  closed_reason TEXT CHECK (closed_reason IS NULL OR closed_reason IN ('undone', 'superseded')),
  closed_note TEXT,
  created_at TEXT NOT NULL,
  CHECK (source_version_id < other_source_version_id),
  CHECK ((closed_at IS NULL) = (closed_reason IS NULL))
);
INSERT INTO record_links_new (id, source_version_id, other_source_version_id, link_kind, rule, source,
                              parent_source_version_id, title_similarity, abstract_similarity, author_agreement,
                              year_gap, merged, undo_json, closed_at, closed_reason, closed_note, created_at)
  SELECT id, source_version_id, other_source_version_id, link_kind, rule, source,
         parent_source_version_id, title_similarity, abstract_similarity, author_agreement,
         year_gap, merged, undo_json, closed_at, closed_reason, closed_note, created_at FROM record_links;
DROP TABLE record_links;
ALTER TABLE record_links_new RENAME TO record_links;
CREATE UNIQUE INDEX record_links_open ON record_links(source_version_id, other_source_version_id) WHERE closed_at IS NULL;
CREATE INDEX record_links_other ON record_links(other_source_version_id);
