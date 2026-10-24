-- deixis:foreign-keys-off
-- Elsevier's article API as a PDF route (D-number in docs/decisions.md): a lookup and its candidates are stored under
-- the provider `elsevier`. Both tables are rebuilt by SQLite's 12-step procedure with every row copied unchanged by column name and the
-- provider list widened by that one name; their indexes are recreated with the same text. No trigger reads them.
CREATE TABLE pdf_discovery_runs_new (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  provider TEXT NOT NULL CHECK (provider IN ('unpaywall', 'openalex', 'crossref', 'core', 'europepmc', 'elsevier', 'web_search')),
  query_text TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'zero_results', 'auth_required', 'rate_limited', 'timeout', 'parse_error', 'failed')),
  result_count INTEGER NOT NULL DEFAULT 0,
  http_status INTEGER,
  error_code TEXT,
  created_at TEXT NOT NULL,
  finished_at TEXT,
  other_title_count INTEGER NOT NULL DEFAULT 0
, retry_after TEXT, attempt_id TEXT);
INSERT INTO pdf_discovery_runs_new (id, research_id, source_version_id, provider, query_text, status, result_count, http_status, error_code, created_at, finished_at, other_title_count, retry_after, attempt_id)
  SELECT id, research_id, source_version_id, provider, query_text, status, result_count, http_status, error_code, created_at, finished_at, other_title_count, retry_after, attempt_id FROM pdf_discovery_runs;
CREATE TABLE pdf_candidates_new (
  id TEXT PRIMARY KEY,
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  discovery_run_id TEXT NOT NULL REFERENCES "pdf_discovery_runs"(id),
  provider TEXT NOT NULL CHECK (provider IN ('unpaywall', 'openalex', 'crossref', 'core', 'europepmc', 'elsevier', 'web_search')),
  candidate_url TEXT NOT NULL,
  landing_url TEXT,
  version_label TEXT,
  license TEXT,
  identity_status TEXT NOT NULL CHECK (identity_status IN ('doi_verified', 'title_verified', 'unverified', 'mismatch')),
  version_status TEXT NOT NULL CHECK (version_status IN ('match', 'different', 'uncertain')),
  access_status TEXT NOT NULL CHECK (access_status IN ('not_attempted', 'downloaded', 'http_error', 'not_pdf', 'too_large', 'timeout', 'blocked_url', 'wrong_type', 'failed')),
  http_status INTEGER,
  error_code TEXT,
  final_url TEXT,
  discovered_at TEXT NOT NULL,
  attempted_at TEXT,
  UNIQUE (source_version_id, provider, candidate_url)
);
INSERT INTO pdf_candidates_new (id, source_version_id, discovery_run_id, provider, candidate_url, landing_url, version_label, license, identity_status, version_status, access_status, http_status, error_code, final_url, discovered_at, attempted_at)
  SELECT id, source_version_id, discovery_run_id, provider, candidate_url, landing_url, version_label, license, identity_status, version_status, access_status, http_status, error_code, final_url, discovered_at, attempted_at FROM pdf_candidates;
DROP TABLE pdf_candidates;
DROP TABLE pdf_discovery_runs;
ALTER TABLE pdf_discovery_runs_new RENAME TO pdf_discovery_runs;
ALTER TABLE pdf_candidates_new RENAME TO pdf_candidates;
CREATE INDEX pdf_discovery_source ON pdf_discovery_runs(source_version_id, created_at);
CREATE UNIQUE INDEX pdf_discovery_attempt ON pdf_discovery_runs(attempt_id) WHERE attempt_id IS NOT NULL;
CREATE INDEX pdf_candidates_source ON pdf_candidates(source_version_id, discovered_at);
