-- Human report edits are append-only; the model text remains on report_claims.
CREATE TABLE report_claim_revisions (
  id TEXT PRIMARY KEY,
  claim_id TEXT NOT NULL REFERENCES report_claims(id),
  kind TEXT NOT NULL CHECK (kind IN ('human_edit', 'human_restore')),
  restored_from TEXT,
  text TEXT NOT NULL,
  warnings_json TEXT NOT NULL DEFAULT '[]',
  note TEXT,
  idempotency_key TEXT UNIQUE,
  created_at TEXT NOT NULL,
  CHECK ((kind = 'human_restore') = (restored_from IS NOT NULL))
);
CREATE INDEX report_claim_revisions_claim ON report_claim_revisions(claim_id, created_at);
ALTER TABLE report_claims ADD COLUMN current_revision_id TEXT REFERENCES report_claim_revisions(id);
ALTER TABLE report_claims ADD COLUMN version INTEGER NOT NULL DEFAULT 1;

CREATE TABLE report_stale_acknowledgements (
  id TEXT PRIMARY KEY,
  report_id TEXT NOT NULL REFERENCES reports(id),
  section_id TEXT NOT NULL,
  change_key TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (report_id, section_id, change_key)
);

CREATE TRIGGER report_claim_revisions_no_update BEFORE UPDATE ON report_claim_revisions
BEGIN SELECT RAISE(ABORT, 'report claim revisions are immutable'); END;
CREATE TRIGGER report_claim_revisions_no_delete BEFORE DELETE ON report_claim_revisions
WHEN NOT EXISTS (SELECT 1 FROM report_claims c JOIN report_sections s ON s.id = c.report_section_id
                 JOIN reports r ON r.id = s.report_id JOIN research_purge_authorizations a ON a.research_id = r.research_id
                 WHERE c.id = OLD.claim_id)
BEGIN SELECT RAISE(ABORT, 'report claim revisions are immutable'); END;

CREATE TRIGGER report_stale_acknowledgements_no_update BEFORE UPDATE ON report_stale_acknowledgements
BEGIN SELECT RAISE(ABORT, 'report stale acknowledgements are immutable'); END;
CREATE TRIGGER report_stale_acknowledgements_no_delete BEFORE DELETE ON report_stale_acknowledgements
WHEN NOT EXISTS (SELECT 1 FROM reports r JOIN research_purge_authorizations a ON a.research_id = r.research_id
                 WHERE r.id = OLD.report_id)
BEGIN SELECT RAISE(ABORT, 'report stale acknowledgements are immutable'); END;
