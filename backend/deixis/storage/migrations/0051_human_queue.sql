-- The human queue (slice 16, D96).
--
-- Which selection a person's queue decision wrote, so undoing that decision releases the selection only while it is
-- still the one the decision wrote. Rows are added, never edited (D71): a decision whose selection moved to a new head
-- of its work gets a second row naming the new head and version, and the decision's current link is its newest row.
-- `research_id` is here so a purge can find the rows without walking the decisions.
CREATE TABLE human_selection_links (
  decision_id TEXT NOT NULL REFERENCES stage_decisions(id),
  research_id TEXT NOT NULL REFERENCES researches(id),
  head TEXT NOT NULL REFERENCES source_versions(id),
  selection_version INTEGER NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX human_selection_links_decision ON human_selection_links(decision_id);
CREATE INDEX human_selection_links_research ON human_selection_links(research_id, head);

CREATE TRIGGER human_selection_links_no_update BEFORE UPDATE ON human_selection_links
BEGIN SELECT RAISE(ABORT, 'human_selection_links are added, never edited'); END;
-- Permanent deletion stays the sole authorized exception, as it is for stage decisions (0038).
CREATE TRIGGER human_selection_links_no_delete BEFORE DELETE ON human_selection_links
WHEN NOT EXISTS (SELECT 1 FROM research_purge_authorizations WHERE research_id = OLD.research_id)
BEGIN SELECT RAISE(ABORT, 'human_selection_links are kept'); END;

-- A person confirmed that this file is the work's own PDF (the fifth queue answer, "PDF doğru, model okusun"). The mark
-- belongs to the file: a new file for the same record carries none and is checked again.
ALTER TABLE source_assets ADD COLUMN identity_confirmed_at TEXT;
