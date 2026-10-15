-- Which scholarly record an uploaded PDF was identified as (D37). NULL: never looked up, or no record passed the match
-- rule; the row then keeps its file-name title. Otherwise JSON: {"provider", "work_id", "basis" ("doi_title" or
-- "title"), "filename_title", "matched_at"}. Only `user_upload` rows carry it.
ALTER TABLE source_versions ADD COLUMN record_match_json TEXT;
