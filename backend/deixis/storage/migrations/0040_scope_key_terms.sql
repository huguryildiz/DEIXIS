-- The user's own English search terms for one scope revision (SW2.1). Code does not translate: a question it cannot
-- read in English is searched only from these, and they are also the one way to correct an extraction by hand.
-- Blocks are separated by ';', synonyms of a block by ',', and a group written 'claim:' or 'not:' fills a side list.
ALTER TABLE scope_revisions ADD COLUMN key_terms TEXT;
