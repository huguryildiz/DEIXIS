-- One decision per record and stage, with the reason code it was decided under (SW9.4-5, SW11).
-- Decisions are added, never edited: a new decision closes the one before it with superseded_at.
CREATE TABLE stage_decisions (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  stage TEXT NOT NULL CHECK (stage IN ('abstract', 'fulltext')),
  outcome TEXT NOT NULL CHECK (outcome IN ('candidate', 'out_of_scope', 'include', 'criterion_not_met', 'unresolved')),
  reason_code TEXT NOT NULL,
  decided_by TEXT NOT NULL CHECK (decided_by IN ('code', 'model_agreement', 'human')),
  next_step TEXT NOT NULL,
  note TEXT,
  scope_revision INTEGER NOT NULL,
  protocol_hash TEXT,
  criterion_hash TEXT,
  step_id TEXT REFERENCES run_steps(id),
  superseded_at TEXT,
  created_at TEXT NOT NULL,
  CHECK ((stage = 'abstract' AND outcome IN ('candidate', 'out_of_scope', 'unresolved'))
      OR (stage = 'fulltext' AND outcome IN ('include', 'criterion_not_met', 'unresolved')))
);
CREATE UNIQUE INDEX stage_decisions_current ON stage_decisions(research_id, source_version_id, stage) WHERE superseded_at IS NULL;
CREATE INDEX stage_decisions_research ON stage_decisions(research_id, stage, outcome);

-- What each model run proposed, kept apart from the decision so a disagreement stays readable (SW11.1, SW11.4).
CREATE TABLE model_proposals (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  stage TEXT NOT NULL CHECK (stage IN ('abstract', 'fulltext')),
  step_id TEXT NOT NULL REFERENCES run_steps(id),
  run_no INTEGER NOT NULL CHECK (run_no IN (1, 2)),
  criterion_part TEXT NOT NULL DEFAULT '',
  label TEXT NOT NULL,
  quote TEXT,
  quote_verified INTEGER CHECK (quote_verified IS NULL OR quote_verified IN (0, 1)),
  quote_passage_id TEXT REFERENCES passages(id),
  quote_page INTEGER,
  created_at TEXT NOT NULL,
  UNIQUE (step_id, source_version_id, criterion_part)
);
CREATE INDEX model_proposals_record ON model_proposals(research_id, source_version_id, stage, run_no);

-- Where each record stood in each ranking signal. Tied records take the average rank, so the rank is REAL (SW7);
-- the combined ranking of one step is stored under signal 'fused'.
CREATE TABLE record_signal_ranks (
  ranking_step_id TEXT NOT NULL REFERENCES run_steps(id),
  research_id TEXT NOT NULL REFERENCES researches(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  signal TEXT NOT NULL,
  rank REAL NOT NULL,
  available INTEGER NOT NULL CHECK (available IN (0, 1)),
  PRIMARY KEY (ranking_step_id, source_version_id, signal)
);
CREATE INDEX record_signal_ranks_research ON record_signal_ranks(research_id, signal, rank);

-- No UPDATE trigger: closing a decision writes superseded_at on the row it closes.
-- Permanent deletion stays the sole authorized exception, as it is for step inputs (0010) and protocols (0037).
CREATE TRIGGER stage_decisions_no_delete BEFORE DELETE ON stage_decisions
WHEN NOT EXISTS (SELECT 1 FROM research_purge_authorizations WHERE research_id = OLD.research_id)
BEGIN SELECT RAISE(ABORT, 'stage_decisions are kept'); END;
CREATE TRIGGER model_proposals_no_delete BEFORE DELETE ON model_proposals
WHEN NOT EXISTS (SELECT 1 FROM research_purge_authorizations WHERE research_id = OLD.research_id)
BEGIN SELECT RAISE(ABORT, 'model_proposals are kept'); END;

-- A selection derived from a stage decision is neither the user's choice nor a raw model proposal, so it needs its own
-- origin. SQLite cannot change a CHECK constraint in place, so the table is rebuilt; nothing references it, and
-- selection_history.origin has no CHECK of its own and is left alone.
CREATE TABLE selections_new (
  research_id TEXT NOT NULL REFERENCES researches(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  state TEXT NOT NULL CHECK (state IN ('included', 'excluded', 'pending')),
  origin TEXT NOT NULL CHECK (origin IN ('default', 'model_proposal', 'code_rule', 'user')),
  user_reason TEXT,
  proposal TEXT CHECK (proposal IS NULL OR proposal IN ('include', 'exclude', 'uncertain')),
  proposal_reason TEXT,
  proposal_basis TEXT,
  proposal_step_id TEXT REFERENCES run_steps(id),
  version INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (research_id, source_version_id)
);
INSERT INTO selections_new (research_id, source_version_id, state, origin, user_reason, proposal, proposal_reason,
                            proposal_basis, proposal_step_id, version, updated_at)
  SELECT research_id, source_version_id, state, origin, user_reason, proposal, proposal_reason,
         proposal_basis, proposal_step_id, version, updated_at FROM selections;
DROP TABLE selections;
ALTER TABLE selections_new RENAME TO selections;
