-- D114: a table made from the research (`evidence_tables.follows_included = 2`) also follows the works read from their
-- abstracts only. The column already takes any integer, so no table changes and nothing is backfilled; this file only
-- records the schema version, so a DEIXIS without D114 refuses this library instead of reading those tables as plain
-- included-source tables (`db.check_schema_known`).
SELECT 1;
