-- What the person asked a research to produce (UI parity S5a, F4): a drafted report (today's flow), the papers only,
-- or a study table (`table`, or `compare` with a comparison frame). Rows from before this migration are reports.
ALTER TABLE researches ADD COLUMN intent TEXT NOT NULL DEFAULT 'report'
  CHECK (intent IN ('report', 'papers', 'table', 'compare'));
-- The comparison question frame a `compare` research stores for its study table; the table itself has no field for it.
ALTER TABLE researches ADD COLUMN comparison_frame TEXT;
