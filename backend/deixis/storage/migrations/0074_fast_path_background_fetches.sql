CREATE TABLE fast_path_background_fetches (
    id TEXT PRIMARY KEY,
    ledger_run_id TEXT NOT NULL REFERENCES fast_path_ledgers(ledger_run_id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    research_id TEXT NOT NULL REFERENCES researches(id) ON DELETE CASCADE,
    scope_revision INTEGER NOT NULL,
    work_id TEXT NOT NULL,
    head TEXT NOT NULL,
    position INTEGER NOT NULL,
    origin TEXT NOT NULL CHECK (origin IN ('in_flight', 'not_started')),
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    attempts INTEGER NOT NULL DEFAULT 0,
    queued_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    outcome_code TEXT,
    UNIQUE (run_id, work_id)
);
CREATE INDEX fast_path_background_ready ON fast_path_background_fetches(status, queued_at, position);
