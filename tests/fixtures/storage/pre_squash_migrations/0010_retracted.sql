-- OpenAlex's retraction flag for a source version (D27). Null is unknown: no OpenAlex read, or OpenAlex sent no boolean.
-- 1 or 0 only from an OpenAlex answer, with the time of that read; a later read without a boolean leaves both as they are.
-- 0009 is left for another branch. The runner applies any file whose number it has not recorded, so a later 0009 still runs.
ALTER TABLE source_versions ADD COLUMN is_retracted INTEGER;
ALTER TABLE source_versions ADD COLUMN is_retracted_at TEXT;
