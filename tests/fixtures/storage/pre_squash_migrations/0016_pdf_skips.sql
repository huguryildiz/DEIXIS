-- A work waiting for the person's PDF that they chose to go on without (D46, "Continue without PDF"). The row only
-- takes the work off the waiting list and its counts; the answer already reads such a work from its abstract. It is
-- keyed by work, not by version or question revision: the person could not find the paper, whichever version or
-- question. Undo deletes the row; a PDF added to any version of
-- the work at or after `skipped_at` ends it (`waiting.skipped`), and normal reading applies.
-- No foreign key on `work_id`: works are joined and split, and a row whose work is gone simply matches nothing.
CREATE TABLE pdf_skips (
  research_id TEXT NOT NULL REFERENCES researches(id),
  work_id TEXT NOT NULL,
  skipped_at TEXT NOT NULL,
  PRIMARY KEY (research_id, work_id)
);
