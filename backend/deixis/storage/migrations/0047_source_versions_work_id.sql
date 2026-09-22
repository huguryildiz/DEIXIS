-- Every "other versions of this work" lookup (work_versions, answer_version, _assign_source_key) scanned the
-- whole table: on the slice 13 smoke run that was 6,891 scans of 7,769 rows for one research view (30 s on the
-- event loop). The work's versions are read by work_id, so the column gets an index.
CREATE INDEX source_versions_work_id ON source_versions(work_id);
