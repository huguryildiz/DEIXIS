-- A cell revision may quote one passage more than once (D43): two different spans of the same passage are two evidence
-- links. The same located words of a passage are still linked once per revision. Nothing references this table, so it is
-- rebuilt with foreign keys on; rowid order, which the views use, is kept by copying in rowid order.
CREATE TABLE cell_evidence_links_new (
  cell_revision_id TEXT NOT NULL REFERENCES cell_revisions(id),
  passage_id TEXT NOT NULL REFERENCES passages(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  step_input_id TEXT REFERENCES step_inputs(id),  -- the StepInput that gave the passage; kept when a proposal is accepted
  anchor_text TEXT,
  anchor_match TEXT CHECK (anchor_match IN ('exact', 'normalized', 'fuzzy'))
);
INSERT INTO cell_evidence_links_new (cell_revision_id, passage_id, source_version_id, step_input_id, anchor_text, anchor_match)
  SELECT cell_revision_id, passage_id, source_version_id, step_input_id, anchor_text, anchor_match FROM cell_evidence_links ORDER BY rowid;
DROP TABLE cell_evidence_links;
ALTER TABLE cell_evidence_links_new RENAME TO cell_evidence_links;
CREATE UNIQUE INDEX cell_evidence_links_anchor ON cell_evidence_links (cell_revision_id, passage_id, IFNULL(anchor_text, ''));

-- Evidence comes from the cell's own source version, never from another version of the same work.
CREATE TRIGGER cell_evidence_same_source BEFORE INSERT ON cell_evidence_links
WHEN NEW.source_version_id IS NOT (SELECT c.source_version_id FROM cell_revisions r JOIN evidence_cells c ON c.id = r.cell_id WHERE r.id = NEW.cell_revision_id)
  OR NEW.source_version_id IS NOT (SELECT source_version_id FROM passages WHERE id = NEW.passage_id)
BEGIN SELECT RAISE(ABORT, 'cell evidence must come from the cell source version'); END;

CREATE TRIGGER cell_evidence_links_no_update BEFORE UPDATE ON cell_evidence_links
BEGIN SELECT RAISE(ABORT, 'cell evidence links are immutable'); END;
CREATE TRIGGER cell_evidence_links_no_delete BEFORE DELETE ON cell_evidence_links
WHEN NOT EXISTS (SELECT 1 FROM cell_revisions r JOIN evidence_cells c ON c.id = r.cell_id JOIN evidence_tables t ON t.id = c.table_id
                 JOIN research_purge_authorizations a ON a.research_id = t.research_id WHERE r.id = OLD.cell_revision_id)
BEGIN SELECT RAISE(ABORT, 'cell evidence links are immutable'); END;
