-- Citation count the provider reported for the record (OpenAlex cited_by_count) and when it was retrieved.
-- NULL: not reported, a record found before this migration, another version of a work, or an uploaded file.
ALTER TABLE source_versions ADD COLUMN cited_by_count INTEGER;
ALTER TABLE source_versions ADD COLUMN cited_by_count_at TEXT;
