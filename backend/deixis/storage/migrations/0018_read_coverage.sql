-- How much of a PDF's extracted text a full-text reading showed the model (audit item 3): the passages shown over the
-- version's pdf passages at the time, their pages, the file's page count and whether every text part was shown. JSON,
-- written with every decision a two-run reading writes; NULL for a decision with no reading and for every decision
-- written before this file.
ALTER TABLE stage_decisions ADD COLUMN read_coverage TEXT;
