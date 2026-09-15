-- Keep citation details that providers deposit, and allow a mistaken attachment to be withdrawn
-- without destroying the immutable passages that may already support an earlier answer.
ALTER TABLE source_versions ADD COLUMN volume TEXT;
ALTER TABLE source_versions ADD COLUMN issue TEXT;
ALTER TABLE source_versions ADD COLUMN pages TEXT;
ALTER TABLE source_assets ADD COLUMN removed_at TEXT;

