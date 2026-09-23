-- Every search that found a candidate, not only the first one the candidate row keeps (D93, slice 14). A row is
-- written with the candidate row, in the same transaction as the page that found it; researches searched before this
-- migration have none, and the run view says their counts were not kept rather than showing zero.
CREATE TABLE candidate_hits (
  research_id TEXT NOT NULL REFERENCES researches(id),
  scope_revision INTEGER NOT NULL,
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  search_run_id TEXT NOT NULL REFERENCES search_runs(id),
  PRIMARY KEY (source_version_id, search_run_id)
);
CREATE INDEX candidate_hits_research ON candidate_hits (research_id, scope_revision);
