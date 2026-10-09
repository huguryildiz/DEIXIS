CREATE TABLE fast_path_late_revisions (
    id TEXT PRIMARY KEY,
    ledger_run_id TEXT NOT NULL UNIQUE REFERENCES runs(id) ON DELETE CASCADE,
    research_id TEXT NOT NULL REFERENCES researches(id) ON DELETE CASCADE,
    scope_revision INTEGER NOT NULL,
    base_answer_id TEXT NOT NULL REFERENCES answers(id) ON DELETE CASCADE,
    base_input_step_id TEXT NOT NULL REFERENCES run_steps(id),
    status TEXT NOT NULL CHECK(status IN ('waiting_fetch','reading','answering','published','skipped','failed')),
    skip_reason TEXT,
    read_run_id TEXT REFERENCES runs(id),
    answer_run_id TEXT REFERENCES runs(id),
    revision_answer_id TEXT REFERENCES answers(id),
    works_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    read_started_at TEXT,
    published_at TEXT
);
CREATE INDEX fast_path_late_revision_open ON fast_path_late_revisions(research_id, status);
