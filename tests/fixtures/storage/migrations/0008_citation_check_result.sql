-- Verify Citations, slice V3 (D99): what one check of a pair read and returned. Columns only; 0002's `citation_checks`
-- is not rebuilt. `plan_revision` is the frozen plan revision the check read and `run_id` the run that sent it;
-- `step_input_id` the stored StepInput of its last attempt; `model_json` the connection, the requested and the resolved
-- model; `raw_output` the model's last answer as it came, kept for a check that could not be completed too;
-- `flags_json` the pair's flags as that revision read them (title mismatch, retraction, identity); `basis_json` the
-- depth read with how many passages were given and not given, and which passage kinds the located quotes came from.
ALTER TABLE citation_checks ADD COLUMN plan_revision INTEGER;
ALTER TABLE citation_checks ADD COLUMN run_id TEXT REFERENCES runs(id) ON DELETE SET NULL;
ALTER TABLE citation_checks ADD COLUMN step_input_id TEXT;
ALTER TABLE citation_checks ADD COLUMN model_json TEXT;
ALTER TABLE citation_checks ADD COLUMN raw_output TEXT;
ALTER TABLE citation_checks ADD COLUMN flags_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE citation_checks ADD COLUMN basis_json TEXT;
-- One check per pair and plan revision: a pair that has one is never sent again for that revision.
CREATE UNIQUE INDEX citation_checks_pair_revision ON citation_checks(pair_id, plan_revision);
