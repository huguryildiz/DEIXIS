CREATE TABLE fast_path_ledgers (
    ledger_run_id TEXT PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
    research_id TEXT NOT NULL REFERENCES researches(id) ON DELETE CASCADE,
    scope_revision INTEGER NOT NULL,
    policy TEXT NOT NULL,
    policy_hash TEXT NOT NULL,
    mode TEXT NOT NULL,
    started_at TEXT NOT NULL,
    answer_run_id TEXT REFERENCES runs(id) ON DELETE SET NULL,
    answer_published_at TEXT,
    answer_outcome TEXT
);

CREATE TABLE fast_path_stages (
    ledger_run_id TEXT NOT NULL REFERENCES fast_path_ledgers(ledger_run_id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    seq INTEGER NOT NULL,
    base_ms INTEGER NOT NULL,
    balance_before_ms INTEGER NOT NULL,
    alloc_ms INTEGER NOT NULL,
    opened_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('open', 'done', 'skipped')),
    done_at TEXT,
    used_ms INTEGER NOT NULL DEFAULT 0,
    rework_ms INTEGER NOT NULL DEFAULT 0,
    overrun_ms INTEGER NOT NULL DEFAULT 0,
    done_generation INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (ledger_run_id, stage)
);

CREATE TABLE fast_path_intervals (
    id TEXT PRIMARY KEY,
    ledger_run_id TEXT NOT NULL REFERENCES fast_path_ledgers(ledger_run_id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    generation INTEGER NOT NULL,
    rework INTEGER NOT NULL CHECK (rework IN (0, 1)),
    started_at TEXT NOT NULL,
    last_checkpoint_at TEXT NOT NULL,
    max_checkpoint_gap_ms INTEGER NOT NULL DEFAULT 0,
    closed_at TEXT,
    close_reason TEXT CHECK (close_reason IN ('stage_done', 'paused', 'stopped', 'recovered')),
    UNIQUE (run_id, stage, attempt)
);
CREATE UNIQUE INDEX fast_path_interval_open ON fast_path_intervals(run_id, stage) WHERE closed_at IS NULL;
