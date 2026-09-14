-- A grounded answer is a sectioned report: each claim carries the heading of its section (D19).
-- Claims saved before this migration have no section.
ALTER TABLE claims ADD COLUMN section TEXT;
