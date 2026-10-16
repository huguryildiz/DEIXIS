-- F4: the day's estimated model spend, kept apart from the researches. One row per paid-API model call (a call on a
-- subscription or a local model costs nothing per call and gets none). There is no foreign key and no cascade: deleting
-- a research deletes its model sessions but never lowers the day's total. `cost_usd` is NULL when no price is known;
-- the call still has its row, so it counts as an unpriced call and never as zero.
CREATE TABLE spend_ledger (
  session_id TEXT PRIMARY KEY,
  day TEXT NOT NULL,
  connection TEXT NOT NULL,
  model TEXT,
  input_tokens INTEGER,
  cached_input_tokens INTEGER,
  output_tokens INTEGER,
  cost_usd REAL,
  basis TEXT NOT NULL CHECK (basis IN ('reported', 'provider_cost', 'estimated_from_text', 'unpriced')),
  recorded_at TEXT NOT NULL
);
CREATE INDEX spend_ledger_day ON spend_ledger(day);
