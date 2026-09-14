-- Selection revision: bumped whenever the included source set changes. Answer StepInputs and
-- answers record the revision their passages were drawn from, so later changes mark them stale.
ALTER TABLE researches ADD COLUMN selection_revision INTEGER NOT NULL DEFAULT 0;
ALTER TABLE step_inputs ADD COLUMN selection_revision INTEGER;
ALTER TABLE answers ADD COLUMN selection_revision INTEGER;

-- Question revision under which a search ran and under which a candidate was last found.
ALTER TABLE search_runs ADD COLUMN scope_revision INTEGER;
ALTER TABLE candidates ADD COLUMN scope_revision INTEGER;
UPDATE search_runs SET scope_revision = (SELECT scope_revision FROM runs WHERE runs.id = search_runs.run_id);
UPDATE candidates SET scope_revision = (SELECT scope_revision FROM search_runs WHERE search_runs.id = candidates.search_run_id);
