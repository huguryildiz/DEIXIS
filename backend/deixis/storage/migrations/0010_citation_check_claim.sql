-- Verify Citations after the V5 pilot (D105): the claim a check reads, kept beside the sentence as written. `claim` is
-- the sentence (or, for a citation in a LaTeX table, its row as "Header: cell" pairs) with the markers cut out and the
-- LaTeX turned into plain text; the model copies its parts from it and coverage is read on it. `claim_context` is a
-- table row's caption, shown to the model and never part of the claim. `sentence` stays the raw text the screen marks
-- the marker in. A draft read before this migration has no claim; its checks read the sentence as before.
-- `parse_reason` says why a marker the parser read was left unrecognized (`table_layout_not_read`), else null.
ALTER TABLE citation_markers ADD COLUMN claim TEXT;
ALTER TABLE citation_markers ADD COLUMN claim_context TEXT;
ALTER TABLE citation_markers ADD COLUMN parse_reason TEXT;
