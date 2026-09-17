-- deixis:foreign-keys-off
-- Review Methodology is assembled in code rather than written by a model, but remains a stored report section.
-- SQLite cannot widen a CHECK in place, so report_sections is rebuilt as runs was in 0035.
CREATE TABLE report_sections_new (
  id TEXT PRIMARY KEY,
  report_id TEXT NOT NULL REFERENCES reports(id),
  section_id TEXT NOT NULL CHECK (section_id IN ('I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'abstract', 'index_terms')),
  step_id TEXT REFERENCES run_steps(id),
  status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'valid', 'draft', 'failed')),
  draft_json TEXT,
  validation_json TEXT,
  word_count INTEGER,
  ordinal INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (report_id, section_id)
);
INSERT INTO report_sections_new (id, report_id, section_id, step_id, status, draft_json, validation_json,
                                 word_count, ordinal, created_at, updated_at)
  SELECT id, report_id, section_id, step_id, status, draft_json, validation_json,
         word_count, ordinal, created_at, updated_at FROM report_sections;
DROP TABLE report_sections;
ALTER TABLE report_sections_new RENAME TO report_sections;
