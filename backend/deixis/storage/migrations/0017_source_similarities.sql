-- Similarity of a screened source's title and abstract to the question it was screened for (D30), per embedding model.
-- Only the source list's "Most relevant" order reads it; screening and the answer do not.
CREATE TABLE source_similarities (
  research_id TEXT NOT NULL REFERENCES researches(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  scope_revision INTEGER NOT NULL,
  model TEXT NOT NULL,
  similarity REAL NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (research_id, source_version_id, scope_revision, model)
);
