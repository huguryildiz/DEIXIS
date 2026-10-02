-- Indexes for the lookups the research view makes once per source version or per stored PDF (P9 H5, D166). Without them
-- each of these scanned its whole table, so the view grew faster than linearly with the number of sources: worst UI
-- time 12 s, median first API call 3.5 s, N=5,000, under parallel load, on the capacity library. Index only; no table or row changes.
-- The first one covers `SELECT DISTINCT provider ... WHERE source_version_id = ? AND scheme = provider ORDER BY provider`.
CREATE INDEX IF NOT EXISTS identifier_mappings_view_lookup ON identifier_mappings(source_version_id, provider, scheme);
-- `WHERE operation_key = ? ORDER BY started_at DESC LIMIT 1`, alone and joined to runs (the unique key leads with run_id).
CREATE INDEX IF NOT EXISTS run_steps_operation ON run_steps(operation_key, started_at);
-- Replaced files only: `WHERE source_version_id = ? AND removal_reason = 'replaced' ORDER BY removed_at DESC`.
CREATE INDEX IF NOT EXISTS source_assets_replaced ON source_assets(source_version_id, removed_at) WHERE removal_reason = 'replaced';
-- `WHERE asset_id = ? AND kind = 'pdf_page' ... GROUP BY physical_page`, once per stored PDF (`ocr_state`); passages were indexed by source version only.
CREATE INDEX IF NOT EXISTS passages_asset ON passages(asset_id, kind);
