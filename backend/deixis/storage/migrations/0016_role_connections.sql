-- Model connection per step role (D28). model_connection stays the answer model's connection.
-- NULL: the role uses model_connection, as for every research created before this migration.
ALTER TABLE scope_revisions ADD COLUMN literature_connection TEXT;
ALTER TABLE scope_revisions ADD COLUMN review_connection TEXT;
