-- Records with one arXiv DOI (an arXiv version, or another provider's record of the same preprint) become versions of
-- one work (D46): each work holding such a record moves to the work of the earliest record with that DOI. Suspected
-- duplicate flags between versions of one work are dropped; candidates and selections are left as they were.
CREATE TEMP TABLE arxiv_work_moves AS
SELECT DISTINCT a.work_id AS old_work_id, (
  SELECT t.work_id FROM source_versions t WHERE t.doi = a.doi ORDER BY t.created_at, t.id LIMIT 1
) AS new_work_id
FROM source_versions a WHERE a.doi LIKE '10.48550/arxiv.%';

DELETE FROM arxiv_work_moves WHERE old_work_id = new_work_id;

UPDATE source_versions SET work_id = (SELECT new_work_id FROM arxiv_work_moves WHERE old_work_id = source_versions.work_id)
WHERE work_id IN (SELECT old_work_id FROM arxiv_work_moves);

DROP TABLE arxiv_work_moves;

DELETE FROM works WHERE id NOT IN (SELECT work_id FROM source_versions);

DELETE FROM suspected_duplicates WHERE (SELECT work_id FROM source_versions WHERE id = source_version_id)
  = (SELECT work_id FROM source_versions WHERE id = other_source_version_id);
