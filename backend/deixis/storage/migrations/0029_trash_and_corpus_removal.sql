-- A source removed from a research keeps its membership row (D50): lists and new work read active memberships, while
-- opening evidence reads any. found_again_at records a later search that found the removed source again.
ALTER TABLE corpus_memberships ADD COLUMN removed_at TEXT;
ALTER TABLE corpus_memberships ADD COLUMN removal_note TEXT;
ALTER TABLE corpus_memberships ADD COLUMN found_again_at TEXT;
CREATE INDEX corpus_memberships_active ON corpus_memberships (research_id) WHERE removed_at IS NULL;

-- A single table's permanent deletion needs its own authorization, as a research's does (D50).
CREATE TABLE table_purge_authorizations (table_id TEXT PRIMARY KEY);

DROP TRIGGER column_revisions_no_delete;
CREATE TRIGGER column_revisions_no_delete BEFORE DELETE ON column_revisions
WHEN NOT EXISTS (SELECT 1 FROM table_columns c JOIN evidence_tables t ON t.id = c.table_id
                 JOIN research_purge_authorizations a ON a.research_id = t.research_id WHERE c.id = OLD.column_id)
 AND NOT EXISTS (SELECT 1 FROM table_columns c JOIN table_purge_authorizations a ON a.table_id = c.table_id WHERE c.id = OLD.column_id)
BEGIN SELECT RAISE(ABORT, 'column revisions are immutable'); END;

DROP TRIGGER cell_revisions_no_delete;
CREATE TRIGGER cell_revisions_no_delete BEFORE DELETE ON cell_revisions
WHEN NOT EXISTS (SELECT 1 FROM evidence_cells c JOIN evidence_tables t ON t.id = c.table_id
                 JOIN research_purge_authorizations a ON a.research_id = t.research_id WHERE c.id = OLD.cell_id)
 AND NOT EXISTS (SELECT 1 FROM evidence_cells c JOIN table_purge_authorizations a ON a.table_id = c.table_id WHERE c.id = OLD.cell_id)
BEGIN SELECT RAISE(ABORT, 'cell revisions are immutable'); END;

DROP TRIGGER cell_evidence_links_no_delete;
CREATE TRIGGER cell_evidence_links_no_delete BEFORE DELETE ON cell_evidence_links
WHEN NOT EXISTS (SELECT 1 FROM cell_revisions r JOIN evidence_cells c ON c.id = r.cell_id JOIN evidence_tables t ON t.id = c.table_id
                 JOIN research_purge_authorizations a ON a.research_id = t.research_id WHERE r.id = OLD.cell_revision_id)
 AND NOT EXISTS (SELECT 1 FROM cell_revisions r JOIN evidence_cells c ON c.id = r.cell_id
                 JOIN table_purge_authorizations a ON a.table_id = c.table_id WHERE r.id = OLD.cell_revision_id)
BEGIN SELECT RAISE(ABORT, 'cell evidence links are immutable'); END;
