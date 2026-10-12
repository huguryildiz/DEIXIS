-- A search plan the person edited (UI parity S23a, F18): the setting and task words, their backups, the inclusion
-- criterion and the optional providers, saved as a new scope revision. A discovery run of that revision searches this
-- plan instead of asking a model for the query, the block labels and the criterion. Null on every other revision: a
-- revision made by another route never carries a plan over, and a stored plan is never edited.
ALTER TABLE scope_revisions ADD COLUMN user_plan_json TEXT;
