-- Model roles (D14). The literature model runs the search plan and screening.
-- NULL: the research model runs them, as for every research created before this migration.
ALTER TABLE scope_revisions ADD COLUMN literature_model TEXT;
ALTER TABLE scope_revisions ADD COLUMN literature_reasoning_effort TEXT;
-- Reviewer: 'default' follows the app-wide reviewer setting at review time, 'custom' uses review_model, 'off' skips review.
ALTER TABLE scope_revisions ADD COLUMN review_mode TEXT NOT NULL DEFAULT 'default' CHECK (review_mode IN ('default', 'custom', 'off'));
ALTER TABLE scope_revisions ADD COLUMN review_model TEXT;
ALTER TABLE scope_revisions ADD COLUMN review_reasoning_effort TEXT;

CREATE TABLE app_settings (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- An additional model's reading of one answer's claims against the passages they cite. It never changes the answer.
-- status 'failed': the review did not produce a valid result; failure_reason says why and the answer stays as it was.
CREATE TABLE answer_reviews (
  id TEXT PRIMARY KEY,
  answer_id TEXT NOT NULL UNIQUE REFERENCES answers(id),
  research_id TEXT NOT NULL REFERENCES researches(id),
  run_id TEXT NOT NULL REFERENCES runs(id),
  step_id TEXT REFERENCES run_steps(id),
  step_input_id TEXT REFERENCES step_inputs(id),
  status TEXT NOT NULL CHECK (status IN ('completed', 'failed')),
  failure_reason TEXT,
  review_json TEXT,
  created_at TEXT NOT NULL
);
