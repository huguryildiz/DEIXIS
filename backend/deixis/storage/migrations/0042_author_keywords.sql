-- The authors' own keywords of a record, as the provider gave them (slice 04b, SW2.4). NULL where the provider
-- carries none: only IEEE Xplore and PubMed name author keywords, and an indexer's controlled terms are never stored
-- here. Read by the sw workflow's expansion step; nothing in the legacy workflow reads it.
ALTER TABLE source_versions ADD COLUMN author_keywords_json TEXT;
