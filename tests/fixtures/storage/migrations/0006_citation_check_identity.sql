-- Verify Citations, slice V2 review (D96): what `identity.check` read on the PDF an entry's text comes from, whichever
-- path chose it (the person's PDF, a PDF the record already held, an open-access copy), against the versions of the
-- entry's record's work, with the file and extraction it read. Null when the text is an abstract or nothing. A frozen
-- plan copies this result into its own revision, so a later upload never changes an earlier plan's warning.
ALTER TABLE citation_bib_entries ADD COLUMN text_identity TEXT CHECK (text_identity IN ('doi', 'title', 'unconfirmed'));
ALTER TABLE citation_bib_entries ADD COLUMN text_identity_asset_id TEXT;
ALTER TABLE citation_bib_entries ADD COLUMN text_identity_extraction TEXT;
-- The identity result each pair's frozen revision read (planned and out-of-cap pairs; null for `no_text`).
ALTER TABLE citation_pairs ADD COLUMN plan_identity_json TEXT;
