-- The English sentence the built-in embedding model reads for a research whose question is not in English
-- (slice 21, D103).
--
-- One row per scope revision, written once and never edited: a revision's similarities are always computed from the
-- same query text. Writing it opens no scope revision, so no decision goes stale. `origin` is 'user' for a sentence
-- the person wrote and 'question' when the person said the question is already in English (the question's own text).
-- A new revision whose question text is unchanged gets a copy of the row in the transaction that writes it.
CREATE TABLE scope_english_questions (
  research_id TEXT NOT NULL REFERENCES researches(id),
  scope_revision INTEGER NOT NULL,
  text TEXT NOT NULL,
  origin TEXT NOT NULL CHECK (origin IN ('user', 'question')),
  created_at TEXT NOT NULL,
  PRIMARY KEY (research_id, scope_revision)
);
