-- Web search results whose title is not the work's title are no longer kept as PDF candidates; the lookup records how
-- many there were, so "no match" stays distinguishable from "no results".
ALTER TABLE pdf_discovery_runs ADD COLUMN other_title_count INTEGER NOT NULL DEFAULT 0;
