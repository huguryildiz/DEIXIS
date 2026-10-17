-- Verify Citations, slice V2 (D96): the text each bibliography entry is read from, the person's own PDF for an entry,
-- and the frozen passage plan's revisions. Columns only; 0002's tables are not rebuilt.
--
-- Per entry: `upload_source_version_id` is the person's PDF attached to that entry (an uploaded source of the draft's
-- internal research) and `upload_identity` what `identity.check` read on its first pages (`doi`, `title` or
-- `unconfirmed`; the last is shown as a flag, never hidden). `text_status` is `pending` until acquisition has decided
-- the entry's text, then `settled`; `available_text` is `full_text`, `abstract` or `metadata_only`; `text_version` is
-- `preprint`, `publisher` or `upload` (null when the record names no version); `text_origin` says where the text came
-- from; `text_note` why an entry has less than full text or is still pending.
ALTER TABLE citation_bib_entries ADD COLUMN upload_source_version_id TEXT REFERENCES source_versions(id) ON DELETE SET NULL;
ALTER TABLE citation_bib_entries ADD COLUMN upload_identity TEXT CHECK (upload_identity IN ('doi', 'title', 'unconfirmed'));
ALTER TABLE citation_bib_entries ADD COLUMN text_status TEXT NOT NULL DEFAULT 'pending' CHECK (text_status IN ('pending', 'settled'));
ALTER TABLE citation_bib_entries ADD COLUMN available_text TEXT CHECK (available_text IN ('full_text', 'abstract', 'metadata_only'));
ALTER TABLE citation_bib_entries ADD COLUMN text_source_version_id TEXT REFERENCES source_versions(id) ON DELETE SET NULL;
ALTER TABLE citation_bib_entries ADD COLUMN text_version TEXT CHECK (text_version IN ('preprint', 'publisher', 'upload'));
ALTER TABLE citation_bib_entries ADD COLUMN text_origin TEXT CHECK (text_origin IN ('person_pdf', 'stored_pdf', 'open_access', 'record'));
ALTER TABLE citation_bib_entries ADD COLUMN text_note TEXT;
ALTER TABLE citation_bib_entries ADD COLUMN text_settled_at TEXT;

-- The draft's plan revision: 0 until the first freeze; the person's re-freeze adds one.
ALTER TABLE citation_drafts ADD COLUMN plan_revision INTEGER NOT NULL DEFAULT 0;
ALTER TABLE citation_drafts ADD COLUMN plan_frozen_at TEXT;

-- The revision a pair's `passage_plan_json` belongs to, and every earlier one it had (status and plan), oldest first,
-- so a re-freeze never overwrites what a preview showed.
ALTER TABLE citation_pairs ADD COLUMN plan_revision INTEGER;
ALTER TABLE citation_pairs ADD COLUMN previous_plans_json TEXT NOT NULL DEFAULT '[]';
