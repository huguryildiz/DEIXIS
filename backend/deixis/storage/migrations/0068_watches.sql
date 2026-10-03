-- deixis:foreign-keys-off
CREATE TABLE runs_new (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  scope_revision INTEGER NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('discovery', 'answer', 'table_columns', 'table_fill', 'cell_recheck', 'research_title', 'pdf_collection', 'pdf_ocr', 'report', 'fulltext_fetch', 'fulltext_adjudication', 'lineage_links', 'claim_decomposition', 'kill_search', 'review', 'watch_check')),
  status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'pause_requested', 'paused', 'completed', 'failed', 'cancelled')),
  stage TEXT NOT NULL CHECK (stage IN ('intake', 'discovery', 'screening', 'inspection', 'answer', 'extraction', 'synthesis', 'candidate', 'claim_check', 'export')),
  pause_reason TEXT, error_json TEXT,
  budget_json TEXT NOT NULL, usage_json TEXT NOT NULL DEFAULT '{}',
  idempotency_key TEXT UNIQUE,
  target_json TEXT,
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
INSERT INTO runs_new SELECT * FROM runs;
DROP TRIGGER kill_searches_run_guard;
DROP TRIGGER owner_reviews_run_guard;
DROP TABLE runs;
ALTER TABLE runs_new RENAME TO runs;
CREATE INDEX runs_status ON runs(status, created_at);
CREATE TRIGGER kill_searches_run_guard BEFORE INSERT ON kill_searches
WHEN NOT EXISTS (
 SELECT 1 FROM runs r JOIN candidate_versions v ON v.id = NEW.candidate_version_id
 JOIN research_candidates c ON c.id = v.candidate_id WHERE r.id = NEW.run_id AND r.kind = 'kill_search' AND r.research_id = c.research_id)
BEGIN SELECT RAISE(ABORT, 'kill-search run kind or research mismatch'); END;
CREATE TRIGGER owner_reviews_run_guard BEFORE INSERT ON owner_reviews
WHEN NOT EXISTS (SELECT 1 FROM runs WHERE id = NEW.run_id AND kind = 'review' AND research_id = NEW.research_id)
BEGIN SELECT RAISE(ABORT, 'owner review requires a review run of its research'); END;

CREATE TABLE watches (
 id TEXT PRIMARY KEY, research_id TEXT NOT NULL REFERENCES researches(id),
 kind TEXT NOT NULL CHECK (kind IN ('protocol_queries','citing_works')),
 mode TEXT NOT NULL DEFAULT 'manual' CHECK (mode IN ('manual','interval')),
 interval_days INTEGER CHECK (interval_days IS NULL OR interval_days IN (1,7,30)),
 enabled INTEGER NOT NULL CHECK (enabled IN (0,1)),
 protocol_record_id TEXT REFERENCES protocol_records(id), scope_revision INTEGER NOT NULL,
 baseline_json TEXT NOT NULL DEFAULT '{}', state_version INTEGER NOT NULL DEFAULT 1,
 last_checked_at TEXT, last_success_at TEXT, next_due_at TEXT,
 idempotency_key TEXT UNIQUE, request_hash TEXT, disable_key TEXT UNIQUE, disable_hash TEXT,
 created_at TEXT NOT NULL, disabled_at TEXT
);
CREATE UNIQUE INDEX watches_enabled_kind ON watches(research_id,kind) WHERE enabled = 1;
CREATE TABLE watch_checks (
 id TEXT PRIMARY KEY, watch_id TEXT NOT NULL REFERENCES watches(id),
 research_id TEXT NOT NULL REFERENCES researches(id), run_id TEXT NOT NULL UNIQUE REFERENCES runs(id),
 trigger TEXT NOT NULL CHECK (trigger IN ('manual','scheduled','catch_up')),
 period_start TEXT NOT NULL, requested_from TEXT, requested_to TEXT NOT NULL,
 config_json TEXT NOT NULL, state_version INTEGER NOT NULL, missed_periods INTEGER NOT NULL DEFAULT 0,
 request_key TEXT UNIQUE, request_hash TEXT, observed_json TEXT, provider_status_json TEXT,
 counts_json TEXT, completed_at TEXT, created_at TEXT NOT NULL, UNIQUE(watch_id,period_start)
) WITHOUT ROWID;
CREATE TABLE watch_reads (
 id TEXT PRIMARY KEY, check_id TEXT NOT NULL REFERENCES watch_checks(id),
 research_id TEXT NOT NULL REFERENCES researches(id), step_id TEXT NOT NULL UNIQUE REFERENCES run_steps(id),
 unit_key TEXT NOT NULL, page_number INTEGER NOT NULL, provider TEXT NOT NULL,
 status TEXT NOT NULL, error_code TEXT, request_description TEXT NOT NULL,
 http_status INTEGER, error_kind TEXT, returned_count INTEGER NOT NULL, dropped_count INTEGER NOT NULL,
 next_cursor TEXT, oldest_publication_date TEXT, newest_publication_date TEXT,
 records_json TEXT NOT NULL, connector_json TEXT, raw_payload_path TEXT,
 payload_sha256 TEXT, payload_file_sha256 TEXT, created_at TEXT NOT NULL,
 UNIQUE(check_id,unit_key,page_number)
) WITHOUT ROWID;
CREATE TABLE watch_seen (
 id TEXT PRIMARY KEY, research_id TEXT NOT NULL REFERENCES researches(id), identity_key TEXT NOT NULL,
 record_json TEXT NOT NULL, merged_into TEXT REFERENCES watch_seen(id),
 first_seen_check_id TEXT NOT NULL REFERENCES watch_checks(id),
 origin TEXT NOT NULL CHECK (origin IN ('baseline','baseline_undated','announced','in_library','notice')),
 identity_uncertain INTEGER NOT NULL CHECK (identity_uncertain IN (0,1)), created_at TEXT NOT NULL
);
CREATE TABLE watch_seen_alias (
 research_id TEXT NOT NULL REFERENCES researches(id), alias TEXT NOT NULL,
 seen_id TEXT NOT NULL REFERENCES watch_seen(id), created_at TEXT NOT NULL,
 UNIQUE(research_id,alias)
);
CREATE TABLE watch_items (
 id TEXT PRIMARY KEY, research_id TEXT NOT NULL REFERENCES researches(id),
 check_id TEXT NOT NULL REFERENCES watch_checks(id), seen_id TEXT NOT NULL REFERENCES watch_seen(id),
 record_json TEXT NOT NULL, kind TEXT NOT NULL CHECK (kind IN ('new_record','notice')),
 found_by_json TEXT NOT NULL, relations_json TEXT NOT NULL, kind_history_json TEXT NOT NULL,
 status TEXT NOT NULL CHECK (status IN ('new','dismissed','added','merged')),
 merged_into_item_id TEXT REFERENCES watch_items(id), dismissed_reason TEXT, dismissed_at TEXT,
 dismiss_key TEXT UNIQUE, dismiss_hash TEXT, created_at TEXT NOT NULL, UNIQUE(research_id,seen_id)
);
CREATE INDEX watch_reads_check ON watch_reads(check_id,unit_key,page_number);
CREATE INDEX watch_seen_research ON watch_seen(research_id,created_at,id);
CREATE INDEX watch_items_research ON watch_items(research_id,status,created_at,id);

CREATE TRIGGER watch_checks_run_guard BEFORE INSERT ON watch_checks
WHEN NOT EXISTS (SELECT 1 FROM runs WHERE id=NEW.run_id AND kind='watch_check' AND research_id=NEW.research_id)
 OR NOT EXISTS (SELECT 1 FROM watches WHERE id=NEW.watch_id AND research_id=NEW.research_id)
BEGIN SELECT RAISE(ABORT,'watch check requires its research watch and run'); END;
CREATE TRIGGER watch_reads_parent_guard BEFORE INSERT ON watch_reads
WHEN NOT EXISTS (SELECT 1 FROM watch_checks c JOIN run_steps s ON s.run_id=c.run_id
 WHERE c.id=NEW.check_id AND c.research_id=NEW.research_id AND s.id=NEW.step_id)
BEGIN SELECT RAISE(ABORT,'watch read requires its check step'); END;
CREATE TRIGGER watch_checks_no_conflicting_insert BEFORE INSERT ON watch_checks
WHEN EXISTS (SELECT 1 FROM watch_checks WHERE id=NEW.id OR run_id=NEW.run_id OR request_key=NEW.request_key
 OR (watch_id=NEW.watch_id AND period_start=NEW.period_start))
BEGIN SELECT RAISE(ABORT,'watch_checks already exists'); END;
CREATE TRIGGER watch_reads_no_conflicting_insert BEFORE INSERT ON watch_reads
WHEN EXISTS (SELECT 1 FROM watch_reads WHERE id=NEW.id OR step_id=NEW.step_id
 OR (check_id=NEW.check_id AND unit_key=NEW.unit_key AND page_number=NEW.page_number))
BEGIN SELECT RAISE(ABORT,'watch_reads already exists'); END;
CREATE TRIGGER watch_checks_no_update BEFORE UPDATE ON watch_checks
WHEN NEW.id IS NOT OLD.id OR NEW.watch_id IS NOT OLD.watch_id OR NEW.research_id IS NOT OLD.research_id
 OR NEW.run_id IS NOT OLD.run_id OR NEW.trigger IS NOT OLD.trigger OR NEW.period_start IS NOT OLD.period_start
 OR NEW.requested_from IS NOT OLD.requested_from OR NEW.requested_to IS NOT OLD.requested_to
 OR NEW.config_json IS NOT OLD.config_json OR NEW.state_version IS NOT OLD.state_version
 OR NEW.missed_periods IS NOT OLD.missed_periods OR NEW.request_key IS NOT OLD.request_key
 OR NEW.request_hash IS NOT OLD.request_hash OR NEW.created_at IS NOT OLD.created_at
 OR (NEW.observed_json IS NOT OLD.observed_json AND OLD.observed_json IS NOT NULL)
 OR (NEW.provider_status_json IS NOT OLD.provider_status_json AND OLD.provider_status_json IS NOT NULL)
 OR (NEW.counts_json IS NOT OLD.counts_json AND OLD.counts_json IS NOT NULL)
 OR (NEW.completed_at IS NOT OLD.completed_at AND OLD.completed_at IS NOT NULL)
BEGIN SELECT RAISE(ABORT,'watch_checks frozen columns are immutable'); END;
CREATE TRIGGER watch_reads_no_update BEFORE UPDATE ON watch_reads
BEGIN SELECT RAISE(ABORT,'watch_reads is immutable'); END;
CREATE TRIGGER watch_checks_no_delete BEFORE DELETE ON watch_checks
WHEN NOT EXISTS (SELECT 1 FROM research_purge_authorizations WHERE research_id=OLD.research_id)
BEGIN SELECT RAISE(ABORT,'watch_checks requires research purge authorization'); END;
CREATE TRIGGER watch_reads_no_delete BEFORE DELETE ON watch_reads
WHEN NOT EXISTS (SELECT 1 FROM research_purge_authorizations WHERE research_id=OLD.research_id)
BEGIN SELECT RAISE(ABORT,'watch_reads requires research purge authorization'); END;
