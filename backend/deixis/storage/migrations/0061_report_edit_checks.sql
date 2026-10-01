CREATE TABLE report_edit_checks (
  id TEXT PRIMARY KEY,
  report_id TEXT NOT NULL REFERENCES reports(id),
  checker_version TEXT NOT NULL,
  input_fingerprint TEXT NOT NULL,
  result_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (report_id, input_fingerprint)
);

CREATE TRIGGER report_edit_checks_no_update BEFORE UPDATE ON report_edit_checks
BEGIN SELECT RAISE(ABORT, 'report edit checks are immutable'); END;
CREATE TRIGGER report_edit_checks_no_delete BEFORE DELETE ON report_edit_checks
WHEN NOT EXISTS (SELECT 1 FROM reports r JOIN research_purge_authorizations a ON a.research_id = r.research_id
                 WHERE r.id = OLD.report_id)
BEGIN SELECT RAISE(ABORT, 'report edit checks are immutable'); END;
