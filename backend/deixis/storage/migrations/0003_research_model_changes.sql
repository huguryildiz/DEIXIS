-- A person's change of the model one role of a research uses (UI parity S17, F10). Append-only: a row is never edited,
-- and only the research purge (which authorizes it and deletes the research) removes it. `from_json` is the role's model
-- as it was in effect just before the change, `to_json` the model chosen. A model step that starts after the change
-- runs on the new model; steps that already finished keep their stored inputs and sessions.
CREATE TABLE research_model_changes (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('answer', 'literature', 'reviewer')),
  from_json TEXT NOT NULL,
  to_json TEXT NOT NULL,
  reason TEXT,
  changed_by TEXT NOT NULL DEFAULT 'person' CHECK (changed_by = 'person'),
  changed_at TEXT NOT NULL
);
CREATE INDEX research_model_changes_research ON research_model_changes(research_id, changed_at);
CREATE TRIGGER research_model_changes_no_update BEFORE UPDATE ON research_model_changes
BEGIN SELECT RAISE(ABORT, 'research_model_changes is append-only'); END;
CREATE TRIGGER research_model_changes_no_delete BEFORE DELETE ON research_model_changes
WHEN NOT EXISTS (SELECT 1 FROM research_purge_authorizations WHERE research_id = OLD.research_id)
BEGIN SELECT RAISE(ABORT, 'research_model_changes requires research purge authorization'); END;
