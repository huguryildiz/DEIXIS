-- Add CORE as its own provenance-bearing PDF discovery provider.

CREATE TABLE pdf_discovery_runs_new (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  provider TEXT NOT NULL CHECK (provider IN ('unpaywall', 'openalex', 'crossref', 'core', 'web_search')),
  query_text TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'zero_results', 'auth_required', 'rate_limited', 'timeout', 'parse_error', 'failed')),
  result_count INTEGER NOT NULL DEFAULT 0,
  http_status INTEGER,
  error_code TEXT,
  created_at TEXT NOT NULL,
  finished_at TEXT
);

CREATE TABLE pdf_candidates_new (
  id TEXT PRIMARY KEY,
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  discovery_run_id TEXT NOT NULL REFERENCES pdf_discovery_runs_new(id),
  provider TEXT NOT NULL CHECK (provider IN ('unpaywall', 'openalex', 'crossref', 'core', 'web_search')),
  candidate_url TEXT NOT NULL,
  landing_url TEXT,
  version_label TEXT,
  license TEXT,
  identity_status TEXT NOT NULL CHECK (identity_status IN ('doi_verified', 'title_verified', 'unverified', 'mismatch')),
  version_status TEXT NOT NULL CHECK (version_status IN ('match', 'different', 'uncertain')),
  access_status TEXT NOT NULL CHECK (access_status IN ('not_attempted', 'downloaded', 'http_error', 'not_pdf', 'too_large', 'timeout', 'blocked_url', 'failed')),
  http_status INTEGER,
  error_code TEXT,
  final_url TEXT,
  discovered_at TEXT NOT NULL,
  attempted_at TEXT,
  UNIQUE (source_version_id, provider, candidate_url)
);

INSERT INTO pdf_discovery_runs_new SELECT * FROM pdf_discovery_runs;
INSERT INTO pdf_candidates_new SELECT * FROM pdf_candidates;
DROP TABLE pdf_candidates;
DROP TABLE pdf_discovery_runs;
ALTER TABLE pdf_discovery_runs_new RENAME TO pdf_discovery_runs;
ALTER TABLE pdf_candidates_new RENAME TO pdf_candidates;
CREATE INDEX pdf_discovery_source ON pdf_discovery_runs(source_version_id, created_at);
CREATE INDEX pdf_candidates_source ON pdf_candidates(source_version_id, discovered_at);
