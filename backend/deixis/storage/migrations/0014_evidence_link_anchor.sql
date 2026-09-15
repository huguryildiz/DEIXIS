-- The passage's own words located from the model's quote (D24), recorded with the evidence link they highlight.
ALTER TABLE evidence_links ADD COLUMN anchor_text TEXT;
ALTER TABLE evidence_links ADD COLUMN anchor_match TEXT CHECK (anchor_match IN ('exact', 'normalized', 'fuzzy'));
