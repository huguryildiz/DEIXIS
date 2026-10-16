-- The provider requests each run made (P2, D31). One row per attempt of `providers.common.send` made for a run (each
-- 429 retry is an attempt of its own) and per OpenAlex PDF lookup by DOI. The row is written just before the attempt is
-- handed to the HTTP client, as not known whether sent (`unknown` 1, `settled_at` NULL), and settled when the attempt
-- ends: `sends` 1 when it went out (one that failed before sending, or waited in vain for a pooled connection, did
-- not), `refusals` 1 when the provider answered it without executing it (HTTP 429 or another refusal). An attempt
-- cancelled while out, or still out when the process stopped, stays not known whether sent; the next start marks the
-- latter `backend_stopped`.
-- AUTOINCREMENT: an id is never reused, so an attempt settling after its research was deleted cannot reach a newer
-- run's row (the settle also checks the run).
CREATE TABLE provider_requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  host TEXT NOT NULL,
  url TEXT NOT NULL,
  sends INTEGER NOT NULL DEFAULT 0 CHECK (sends IN (0, 1)),
  refusals INTEGER NOT NULL DEFAULT 0 CHECK (refusals IN (0, 1) AND refusals <= sends),
  unknown INTEGER NOT NULL DEFAULT 1 CHECK (unknown IN (0, 1) AND sends + unknown <= 1),
  delivery_class TEXT,
  http_status INTEGER,
  started_at TEXT NOT NULL,
  settled_at TEXT
);
CREATE INDEX provider_requests_run ON provider_requests(run_id, host);

-- The runs that existed before requests were recorded: their count is not known and is never shown as 0.
CREATE TABLE provider_requests_unrecorded_runs (
  run_id TEXT PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE
) WITHOUT ROWID;
INSERT INTO provider_requests_unrecorded_runs (run_id) SELECT id FROM runs;
