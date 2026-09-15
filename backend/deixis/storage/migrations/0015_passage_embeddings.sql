-- Passage vectors for semantic retrieval (D27): one row per passage and embedding model, unit-length float32 values.
CREATE TABLE passage_embeddings (
  passage_id TEXT NOT NULL REFERENCES passages(id),
  model TEXT NOT NULL,
  dimensions INTEGER NOT NULL,
  vector BLOB NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (passage_id, model)
);
