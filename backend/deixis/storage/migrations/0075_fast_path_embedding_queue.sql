CREATE TABLE fast_path_embedding_queue (
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    class INTEGER NOT NULL CHECK (class IN (0, 1, 2)),
    request_index INTEGER NOT NULL,
    position INTEGER NOT NULL,
    source_version_id TEXT NOT NULL REFERENCES source_versions(id) ON DELETE CASCADE,
    search_run_id TEXT REFERENCES search_runs(id) ON DELETE SET NULL,
    enqueued_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'embedded', 'from_store', 'unembedded_at_cutoff')),
    embedded_at TEXT,
    cutoff_at TEXT,
    PRIMARY KEY (run_id, class, request_index, position),
    UNIQUE (run_id, source_version_id)
);
CREATE INDEX fast_path_embedding_pending ON fast_path_embedding_queue(run_id, status, class, request_index, position);
