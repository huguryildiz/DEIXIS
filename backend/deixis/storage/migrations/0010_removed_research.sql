-- Trash keeps provenance intact. Permanent deletion is the sole authorized exception to immutable step inputs.
ALTER TABLE researches ADD COLUMN trashed_at TEXT;
CREATE TABLE research_purge_authorizations (research_id TEXT PRIMARY KEY);
DROP TRIGGER step_inputs_no_delete;
CREATE TRIGGER step_inputs_no_delete BEFORE DELETE ON step_inputs
WHEN NOT EXISTS (SELECT 1 FROM research_purge_authorizations WHERE research_id = OLD.research_id)
BEGIN SELECT RAISE(ABORT, 'step_inputs are immutable'); END;
