-- Which seed linked to which OpenAlex work, in which direction, in which discovery run (D95, slice 15). A link is
-- written whether or not the linked work passed the chain's filter: one that did not pass has no record, no membership
-- and no candidate, so this row is all that says it was reached. `source_version_id` is the record the linked work
-- became when it passed. A resumed run finds its rows here and writes none of them again.
CREATE TABLE chain_links (
  research_id TEXT NOT NULL REFERENCES researches(id),
  scope_revision INTEGER NOT NULL,
  run_id TEXT NOT NULL REFERENCES runs(id),
  seed_source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  linked_openalex_id TEXT NOT NULL,     -- OpenAlex work id, short form (W…)
  direction TEXT NOT NULL CHECK (direction IN ('backward', 'forward')),
  passed_filter INTEGER NOT NULL CHECK (passed_filter IN (0, 1)),
  source_version_id TEXT REFERENCES source_versions(id),
  PRIMARY KEY (run_id, seed_source_version_id, linked_openalex_id, direction)
);
CREATE INDEX chain_links_research ON chain_links (research_id, scope_revision);
