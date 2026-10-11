-- Works the person keeps in the Library on their own (UI parity S19a, F14), apart from any research. One row per source
-- version: a preprint and its published version saved together stay two rows, never one merged record. A saved item
-- keeps its source record, passages and file when every research that held it is purged or loses it.
-- `origin` is how the item came in. `metadata_origin` says whose bibliographic fields the record carries: a provider's,
-- or the person's own (an uploaded file's name, an imported .bib/.ris entry) until a provider confirms them, which
-- `metadata_confirmed_by` / `metadata_confirmed_at` record.
CREATE TABLE library_items (
  source_version_id TEXT PRIMARY KEY REFERENCES source_versions(id),
  origin TEXT NOT NULL CHECK (origin IN ('saved', 'upload', 'zotero_import', 'bibtex_import', 'ris_import')),
  metadata_origin TEXT NOT NULL CHECK (metadata_origin IN ('provider', 'user_supplied')),
  metadata_confirmed_by TEXT,
  metadata_confirmed_at TEXT,
  added_at TEXT NOT NULL,
  CHECK ((metadata_confirmed_by IS NULL) = (metadata_confirmed_at IS NULL))
);
