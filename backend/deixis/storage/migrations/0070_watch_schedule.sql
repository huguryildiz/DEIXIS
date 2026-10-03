ALTER TABLE watches ADD COLUMN catch_up INTEGER CHECK (catch_up IS NULL OR catch_up IN (0,1));
ALTER TABLE watches ADD COLUMN schedule_version INTEGER NOT NULL DEFAULT 1 CHECK (schedule_version >= 1);
UPDATE watches SET mode='manual' WHERE mode='interval';
UPDATE watches SET interval_days=NULL,next_due_at=NULL WHERE mode='manual';

CREATE TRIGGER watches_schedule_insert BEFORE INSERT ON watches
WHEN (NEW.mode='manual' AND (NEW.interval_days IS NOT NULL OR NEW.catch_up IS NOT NULL OR NEW.next_due_at IS NOT NULL))
 OR (NEW.mode='interval' AND (NEW.interval_days IS NULL OR NEW.catch_up IS NULL OR (NEW.enabled=1 AND NEW.next_due_at IS NULL)))
BEGIN SELECT RAISE(ABORT,'incoherent watch schedule'); END;
CREATE TRIGGER watches_schedule_update BEFORE UPDATE ON watches
WHEN (NEW.mode='manual' AND (NEW.interval_days IS NOT NULL OR NEW.catch_up IS NOT NULL OR NEW.next_due_at IS NOT NULL))
 OR (NEW.mode='interval' AND (NEW.interval_days IS NULL OR NEW.catch_up IS NULL OR (NEW.enabled=1 AND NEW.next_due_at IS NULL)))
BEGIN SELECT RAISE(ABORT,'incoherent watch schedule'); END;

CREATE TABLE watch_schedule_changes (
 id TEXT PRIMARY KEY, watch_id TEXT NOT NULL REFERENCES watches(id), research_id TEXT NOT NULL REFERENCES researches(id),
 schedule_version INTEGER NOT NULL CHECK (schedule_version >= 2),
 mode TEXT NOT NULL CHECK (mode IN ('manual','interval')),
 interval_days INTEGER CHECK (interval_days IS NULL OR interval_days IN (1,7,30)),
 catch_up INTEGER CHECK (catch_up IS NULL OR catch_up IN (0,1)), next_due_at TEXT,
 request_key TEXT NOT NULL UNIQUE, request_hash TEXT NOT NULL, created_at TEXT NOT NULL,
 UNIQUE(watch_id,schedule_version),
 CHECK ((mode='manual' AND interval_days IS NULL AND catch_up IS NULL AND next_due_at IS NULL)
     OR (mode='interval' AND interval_days IS NOT NULL AND catch_up IS NOT NULL AND next_due_at IS NOT NULL))
) WITHOUT ROWID;
CREATE TABLE watch_gaps (
 id TEXT PRIMARY KEY, watch_id TEXT NOT NULL REFERENCES watches(id), research_id TEXT NOT NULL REFERENCES researches(id),
 opening_id TEXT NOT NULL, first_missed_due TEXT NOT NULL, last_missed_due TEXT NOT NULL,
 missed_periods INTEGER NOT NULL CHECK (missed_periods >= 1), observed_until TEXT, noticed_at TEXT NOT NULL,
 schedule_version INTEGER NOT NULL CHECK (schedule_version >= 1),
 outcome TEXT NOT NULL CHECK (outcome IN ('catch_up_chosen','catch_up_off','opening_cap','one_per_research','not_eligible','changed_before_record')),
 outcome_reason TEXT, next_due_at TEXT, created_at TEXT NOT NULL, UNIQUE(watch_id,opening_id)
) WITHOUT ROWID;
CREATE TRIGGER watch_schedule_changes_parent_guard BEFORE INSERT ON watch_schedule_changes
WHEN NOT EXISTS (SELECT 1 FROM watches WHERE id=NEW.watch_id AND research_id=NEW.research_id)
BEGIN SELECT RAISE(ABORT,'schedule change requires its research watch'); END;
CREATE TRIGGER watch_gaps_parent_guard BEFORE INSERT ON watch_gaps
WHEN NOT EXISTS (SELECT 1 FROM watches WHERE id=NEW.watch_id AND research_id=NEW.research_id)
BEGIN SELECT RAISE(ABORT,'gap requires its research watch'); END;
CREATE TRIGGER watch_schedule_changes_no_conflicting_insert BEFORE INSERT ON watch_schedule_changes
WHEN EXISTS (SELECT 1 FROM watch_schedule_changes WHERE id=NEW.id OR request_key=NEW.request_key
 OR (watch_id=NEW.watch_id AND schedule_version=NEW.schedule_version))
BEGIN SELECT RAISE(ABORT,'watch_schedule_changes already exists'); END;
CREATE TRIGGER watch_gaps_no_conflicting_insert BEFORE INSERT ON watch_gaps
WHEN EXISTS (SELECT 1 FROM watch_gaps WHERE id=NEW.id OR (watch_id=NEW.watch_id AND opening_id=NEW.opening_id))
BEGIN SELECT RAISE(ABORT,'watch_gaps already exists'); END;
CREATE TRIGGER watch_schedule_changes_no_update BEFORE UPDATE ON watch_schedule_changes
BEGIN SELECT RAISE(ABORT,'watch_schedule_changes is immutable'); END;
CREATE TRIGGER watch_gaps_no_update BEFORE UPDATE ON watch_gaps
BEGIN SELECT RAISE(ABORT,'watch_gaps is immutable'); END;
CREATE TRIGGER watch_schedule_changes_no_delete BEFORE DELETE ON watch_schedule_changes
WHEN NOT EXISTS (SELECT 1 FROM research_purge_authorizations WHERE research_id=OLD.research_id)
BEGIN SELECT RAISE(ABORT,'watch_schedule_changes requires research purge authorization'); END;
CREATE TRIGGER watch_gaps_no_delete BEFORE DELETE ON watch_gaps
WHEN NOT EXISTS (SELECT 1 FROM research_purge_authorizations WHERE research_id=OLD.research_id)
BEGIN SELECT RAISE(ABORT,'watch_gaps requires research purge authorization'); END;
