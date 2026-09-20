-- What two records are to each other when no DOI made them one record: the rule that decided it, the scores it read
-- and what a merge moved, so the merge can be undone (SW6.9).
-- Works are library-wide (D46), so a link is too: the table carries no research identifier, and a row goes only when
-- one of its records is permanently deleted. The pair is always stored with the smaller identifier on the left; an
-- artifact and a notice keep their direction in parent_source_version_id.
CREATE TABLE record_links (
  id TEXT PRIMARY KEY,
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  other_source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  link_kind TEXT NOT NULL CHECK (link_kind IN ('same_work', 'extended_version', 'probable_version', 'related_suspected',
                                               'artifact_of', 'notice_of')),
  rule TEXT NOT NULL,
  -- Slice 05 widens this with 'semantic_scholar' and 'crossref_relation'.
  source TEXT NOT NULL CHECK (source IN ('text', 'arxiv_doi')),
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
CREATE UNIQUE INDEX record_links_open ON record_links(source_version_id, other_source_version_id) WHERE closed_at IS NULL;
CREATE INDEX record_links_other ON record_links(other_source_version_id);
