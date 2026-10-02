-- NULL denotes a legacy revision whose complete original citation set remains effective.
ALTER TABLE report_claim_revisions ADD COLUMN link_count INTEGER CHECK (link_count >= 0);
ALTER TABLE report_claim_revisions ADD COLUMN request_hash TEXT;

CREATE TABLE report_claim_revision_links (
  revision_id TEXT NOT NULL REFERENCES report_claim_revisions(id),
  link_id TEXT NOT NULL REFERENCES report_citation_links(id),
  PRIMARY KEY (revision_id, link_id)
) WITHOUT ROWID;

-- REPLACE bypasses delete triggers when recursive_triggers is off, including rowid conflicts.
CREATE TRIGGER report_claim_revisions_no_conflicting_insert BEFORE INSERT ON report_claim_revisions
WHEN EXISTS (SELECT 1 FROM report_claim_revisions WHERE id = NEW.id OR rowid = NEW.rowid)
  OR (NEW.idempotency_key IS NOT NULL AND EXISTS (
      SELECT 1 FROM report_claim_revisions WHERE idempotency_key = NEW.idempotency_key))
BEGIN SELECT RAISE(ABORT, 'report claim revision already exists'); END;

CREATE TRIGGER report_claim_revision_links_no_conflicting_insert BEFORE INSERT ON report_claim_revision_links
WHEN EXISTS (SELECT 1 FROM report_claim_revision_links
             WHERE revision_id = NEW.revision_id AND link_id = NEW.link_id)
BEGIN SELECT RAISE(ABORT, 'report revision link already exists'); END;

CREATE TRIGGER report_claim_revision_links_sealed BEFORE INSERT ON report_claim_revision_links
WHEN (SELECT link_count FROM report_claim_revisions WHERE id = NEW.revision_id) IS NULL
  OR (SELECT COUNT(*) FROM report_claim_revision_links WHERE revision_id = NEW.revision_id)
     >= (SELECT link_count FROM report_claim_revisions WHERE id = NEW.revision_id)
  OR (SELECT claim_id FROM report_citation_links WHERE id = NEW.link_id)
     IS NOT (SELECT claim_id FROM report_claim_revisions WHERE id = NEW.revision_id)
BEGIN SELECT RAISE(ABORT, 'report revision citation set is sealed or belongs to another claim'); END;

CREATE TRIGGER report_claim_revision_links_no_update BEFORE UPDATE ON report_claim_revision_links
BEGIN SELECT RAISE(ABORT, 'report revision links are immutable'); END;
CREATE TRIGGER report_claim_revision_links_no_delete BEFORE DELETE ON report_claim_revision_links
WHEN NOT EXISTS (SELECT 1 FROM report_claim_revisions v JOIN report_claims c ON c.id = v.claim_id
                 JOIN report_sections s ON s.id = c.report_section_id JOIN reports r ON r.id = s.report_id
                 JOIN research_purge_authorizations a ON a.research_id = r.research_id
                 WHERE v.id = OLD.revision_id)
BEGIN SELECT RAISE(ABORT, 'report revision links are immutable'); END;
