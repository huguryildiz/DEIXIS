-- A report version is opened by the person (D57): a new question, a new search, an answer they start, or a follow-up
-- that asks for the report to change. An answer the application writes on its own over the same version (a late full
-- text, `late_revision`) keeps that version's number and counts up `report_revision` instead: 0 is the version as first
-- written, 1 its first update, and so on. Existing valid answers are revision 0; their numbers are not rewritten.
ALTER TABLE answers ADD COLUMN report_revision INTEGER;
UPDATE answers SET report_revision = 0 WHERE report_version IS NOT NULL;
DROP INDEX answers_report_version;
CREATE UNIQUE INDEX answers_report_version ON answers (research_id, report_version, report_revision) WHERE report_version IS NOT NULL;
