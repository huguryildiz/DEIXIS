-- Recovery history is removed only within an explicit source/research purge.
CREATE TABLE recovery_purge_authorizations (sha256 TEXT PRIMARY KEY) WITHOUT ROWID;

CREATE TRIGGER asset_recovery_operations_delete_guard BEFORE DELETE ON asset_recovery_operations
WHEN NOT EXISTS (SELECT 1 FROM recovery_purge_authorizations WHERE sha256 = OLD.expected_sha256)
BEGIN SELECT RAISE(ABORT, 'recovery history requires purge authorization'); END;

CREATE TRIGGER asset_file_observations_delete_guard BEFORE DELETE ON asset_file_observations
WHEN NOT EXISTS (SELECT 1 FROM recovery_purge_authorizations WHERE sha256 = OLD.expected_sha256)
BEGIN SELECT RAISE(ABORT, 'recovery history requires purge authorization'); END;
