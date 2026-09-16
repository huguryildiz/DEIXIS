-- A structurally valid answer is a report and gets a stable number within its research, counted only over valid answers
-- and fixed when it is saved. Clarifications, no-evidence results and unverified drafts do not take a number.
ALTER TABLE answers ADD COLUMN report_version INTEGER;

UPDATE answers SET report_version = (
  SELECT COUNT(*) FROM answers b
  WHERE b.research_id = answers.research_id AND b.status = 'structurally_valid'
    AND (b.created_at < answers.created_at OR (b.created_at = answers.created_at AND b.rowid <= answers.rowid))
) WHERE status = 'structurally_valid';

CREATE UNIQUE INDEX answers_report_version ON answers (research_id, report_version) WHERE report_version IS NOT NULL;
