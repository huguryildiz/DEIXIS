-- Two source versions of one research that may describe the same work, recorded without merging them.
-- basis 'same_title': normalized titles are equal. 'published_doi': a preprint record names the other record's DOI.
-- Each pair is stored once, with the smaller source version id first.
CREATE TABLE suspected_duplicates (
  research_id TEXT NOT NULL REFERENCES researches(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  other_source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  basis TEXT NOT NULL CHECK (basis IN ('same_title', 'published_doi')),
  created_at TEXT NOT NULL,
  PRIMARY KEY (research_id, source_version_id, other_source_version_id)
);
