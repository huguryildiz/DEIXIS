-- What the person asked a research to produce (UI parity S5a, F4): a drafted report (today's flow), the papers only,
-- or a study table (`table`, or `compare`, whose column suggestions get a comparison frame written from the question
-- of the revision they run under). Rows from before this migration are reports.
ALTER TABLE researches ADD COLUMN intent TEXT NOT NULL DEFAULT 'report'
  CHECK (intent IN ('report', 'papers', 'table', 'compare'));
