-- A question revision names the revision it was opened from and the research title before it, and can be withdrawn
-- while nothing but its title run and a person's selection decisions was made under it (D67). A withdrawn revision
-- stays as history and its number is never used again: a new revision takes the highest number plus one. Before this
-- file a revision was always opened from the one before it, so `parent_revision` is that for the existing rows; the
-- title before them was not kept and stays NULL.
ALTER TABLE scope_revisions ADD COLUMN parent_revision INTEGER;
ALTER TABLE scope_revisions ADD COLUMN title_before TEXT;
ALTER TABLE scope_revisions ADD COLUMN withdrawn_at TEXT;
UPDATE scope_revisions SET parent_revision = revision - 1 WHERE revision > 1;
