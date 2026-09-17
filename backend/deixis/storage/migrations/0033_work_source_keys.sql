-- A short author–year key per work, such as "Nakano13" (D59). It is given once, across the whole library, and kept; the
-- basis records whether it came from an author or, lacking one, from the title, which a later author may replace.
-- Existing works get their keys at startup (Store.assign_source_keys), in the order they were stored.
ALTER TABLE works ADD COLUMN source_key TEXT;
ALTER TABLE works ADD COLUMN source_key_basis TEXT CHECK (source_key_basis IN ('author', 'title'));
CREATE UNIQUE INDEX works_source_key ON works (source_key COLLATE NOCASE) WHERE source_key IS NOT NULL;
