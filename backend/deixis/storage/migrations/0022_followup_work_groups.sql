-- D66: a follow-up answer that groups works stores the counts the application made from it, frozen when the turn is
-- published: per group the distinct works with their membership labels, the works left ambiguous or without evidence,
-- the works sent but not classified, and the works the evidence table names whose passages were not sent. NULL for a
-- turn whose answer groups no works, and for every turn published before 0022.
ALTER TABLE followup_turns ADD COLUMN work_groups_json TEXT;
