-- Existing mixed researches retain their question-only searches. New mixed researches may require a selected PDF seed.
ALTER TABLE scope_revisions ADD COLUMN seed_mode TEXT NOT NULL DEFAULT 'question_only'
  CHECK (seed_mode IN ('question_only', 'uploaded_seed'));
ALTER TABLE scope_revisions ADD COLUMN seed_snapshot_json TEXT;
