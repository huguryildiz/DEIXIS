-- D190: additive occurrence identity; legacy input bytes remain unobserved.
CREATE TABLE asset_recovery_operations (
  id TEXT NOT NULL PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('file_restore', 'text_retry')),
  asset_id TEXT REFERENCES source_assets(id),
  research_id TEXT,
  expected_sha256 TEXT NOT NULL CHECK (length(expected_sha256) = 64),
  expected_byte_size INTEGER NOT NULL,
  baseline_extraction_id TEXT REFERENCES asset_extractions(id) DEFERRABLE INITIALLY DEFERRED,
  baseline_profile TEXT,
  mode TEXT CHECK (mode IS NULL OR mode = 'retry_failed_or_partial'),
  idempotency_key TEXT NOT NULL UNIQUE,
  request_fingerprint TEXT NOT NULL,
  lifecycle TEXT NOT NULL CHECK (lifecycle IN ('running', 'completed', 'interrupted')),
  outcome TEXT CHECK (outcome IN ('promoted', 'diagnosis_updated', 'rejected', 'no_change', 'refused', 'file_reused', 'file_restored', 'file_refused')),
  reason TEXT,
  decision_code TEXT CHECK (decision_code IS NULL OR decision_code IN ('no_change', 'recovered_text', 'password_diagnosed', 'no_text_diagnosed', 'text_updated', 'recovered_from_corrupt_input', 'candidate_failed', 'augmented_text_would_be_lost', 'status_worse', 'page_count_changed', 'legacy_page_count_untrusted', 'text_page_lost', 'upgraded', 'fewer_text_pages', 'ocr_found_no_text', 'input_not_verified')),
  before_observation_id TEXT REFERENCES asset_file_observations(id) DEFERRABLE INITIALLY DEFERRED,
  after_observation_id TEXT REFERENCES asset_file_observations(id) DEFERRABLE INITIALLY DEFERRED,
  input_observation_id TEXT REFERENCES asset_file_observations(id) DEFERRABLE INITIALLY DEFERRED,
  old_coverage_json TEXT,
  new_coverage_json TEXT,
  created_at TEXT NOT NULL,
  finished_at TEXT,
  CHECK (kind <> 'text_retry' OR (asset_id IS NOT NULL AND mode IS NOT NULL AND baseline_extraction_id IS NOT NULL AND baseline_profile IS NOT NULL)),
  CHECK ((finished_at IS NULL) = (lifecycle = 'running')),
  CHECK ((outcome IS NOT NULL) = (lifecycle = 'completed'))
) WITHOUT ROWID;
CREATE INDEX asset_recovery_operations_asset_created ON asset_recovery_operations(asset_id, created_at);
CREATE UNIQUE INDEX asset_recovery_operations_one_running ON asset_recovery_operations(asset_id)
  WHERE kind = 'text_retry' AND lifecycle = 'running';

CREATE TABLE asset_file_observations (
  id TEXT NOT NULL PRIMARY KEY,
  operation_id TEXT REFERENCES asset_recovery_operations(id),
  kind TEXT NOT NULL CHECK (kind IN ('before_restore', 'after_restore', 'extraction_input')),
  storage_path TEXT NOT NULL,
  expected_sha256 TEXT NOT NULL CHECK (length(expected_sha256) = 64),
  expected_byte_size INTEGER NOT NULL,
  observed_sha256 TEXT,
  observed_byte_size INTEGER,
  integrity TEXT NOT NULL CHECK (integrity IN ('verified', 'mismatch', 'missing', 'legacy_unknown')),
  retained_filename TEXT,
  observed_at TEXT NOT NULL,
  CHECK (
    (integrity = 'verified' AND observed_sha256 IS NOT NULL AND observed_byte_size IS NOT NULL
      AND observed_sha256 = expected_sha256 AND observed_byte_size = expected_byte_size)
    OR (integrity = 'mismatch' AND observed_sha256 IS NOT NULL AND observed_byte_size IS NOT NULL
      AND (observed_sha256 <> expected_sha256 OR observed_byte_size <> expected_byte_size))
    OR (integrity IN ('missing', 'legacy_unknown') AND observed_sha256 IS NULL AND observed_byte_size IS NULL)
  ),
  CHECK (retained_filename IS NULL OR (kind = 'before_restore' AND observed_sha256 IS NOT NULL))
) WITHOUT ROWID;
CREATE INDEX asset_file_observations_operation ON asset_file_observations(operation_id);

ALTER TABLE asset_extractions ADD COLUMN extractor_profile TEXT NOT NULL DEFAULT 'unknown';
UPDATE asset_extractions SET extractor_profile = extraction_version;
ALTER TABLE asset_extractions ADD COLUMN recovery_operation_id TEXT REFERENCES asset_recovery_operations(id);
ALTER TABLE asset_extractions ADD COLUMN baseline_extraction_id TEXT REFERENCES asset_extractions(id);
ALTER TABLE asset_extractions ADD COLUMN input_observation_id TEXT REFERENCES asset_file_observations(id);
ALTER TABLE asset_extractions ADD COLUMN diagnostic_only INTEGER NOT NULL DEFAULT 0 CHECK (diagnostic_only IN (0, 1));
ALTER TABLE asset_extractions ADD COLUMN decision_code TEXT CHECK (decision_code IS NULL OR decision_code IN ('no_change', 'recovered_text', 'password_diagnosed', 'no_text_diagnosed', 'text_updated', 'recovered_from_corrupt_input', 'candidate_failed', 'augmented_text_would_be_lost', 'status_worse', 'page_count_changed', 'legacy_page_count_untrusted', 'text_page_lost', 'upgraded', 'fewer_text_pages', 'ocr_found_no_text', 'input_not_verified'));
CREATE UNIQUE INDEX asset_extractions_recovery_operation ON asset_extractions(recovery_operation_id)
  WHERE recovery_operation_id IS NOT NULL;

CREATE TRIGGER asset_file_observations_no_update BEFORE UPDATE ON asset_file_observations
BEGIN SELECT RAISE(ABORT, 'file observations are immutable'); END;
CREATE TRIGGER asset_file_observations_no_conflicting_insert BEFORE INSERT ON asset_file_observations
WHEN EXISTS (SELECT 1 FROM asset_file_observations WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'file observations are immutable'); END;

CREATE TRIGGER asset_extractions_no_update BEFORE UPDATE ON asset_extractions
WHEN NEW.id IS NOT OLD.id
  OR NEW.asset_id IS NOT OLD.asset_id
  OR NEW.extraction_version IS NOT OLD.extraction_version
  OR NEW.status IS NOT OLD.status
  OR NEW.error IS NOT OLD.error
  OR NEW.page_count IS NOT OLD.page_count
  OR NEW.text_pages IS NOT OLD.text_pages
  OR NEW.passage_count IS NOT OLD.passage_count
  OR NEW.rejection_reason IS NOT OLD.rejection_reason
  OR NEW.created_at IS NOT OLD.created_at
  OR NEW.math_json IS NOT OLD.math_json
  OR NEW.ocr_json IS NOT OLD.ocr_json
  OR NEW.extractor_profile IS NOT OLD.extractor_profile
  OR NEW.recovery_operation_id IS NOT OLD.recovery_operation_id
  OR NEW.baseline_extraction_id IS NOT OLD.baseline_extraction_id
  OR NEW.input_observation_id IS NOT OLD.input_observation_id
  OR NEW.diagnostic_only IS NOT OLD.diagnostic_only
  OR NEW.decision_code IS NOT OLD.decision_code
  OR (NEW.outcome IS NOT OLD.outcome AND NOT (
    (OLD.outcome = 'current' AND NEW.outcome = 'superseded') OR
    (OLD.outcome = 'superseded' AND NEW.outcome = 'current')))
BEGIN SELECT RAISE(ABORT, 'extraction content is immutable'); END;

CREATE TRIGGER asset_extractions_baseline_same_asset BEFORE INSERT ON asset_extractions
WHEN NEW.baseline_extraction_id IS NOT NULL AND NOT EXISTS (
  SELECT 1 FROM asset_extractions WHERE id = NEW.baseline_extraction_id AND asset_id = NEW.asset_id)
BEGIN SELECT RAISE(ABORT, 'extraction baseline belongs to another asset'); END;
CREATE TRIGGER asset_extractions_recovery_shape BEFORE INSERT ON asset_extractions
WHEN (NEW.recovery_operation_id IS NOT NULL AND (
    NOT EXISTS (SELECT 1 FROM asset_recovery_operations WHERE id = NEW.recovery_operation_id
      AND kind = 'text_retry' AND asset_id = NEW.asset_id)
    OR NEW.extraction_version IS NOT (NEW.extractor_profile || '+reextract-' || NEW.recovery_operation_id)))
  OR (instr(NEW.extraction_version, '+reextract-') = 0 AND NEW.extractor_profile IS NOT NEW.extraction_version)
  OR (NEW.extractor_profile = 'unknown' AND NEW.extraction_version <> 'unknown')
BEGIN SELECT RAISE(ABORT, 'invalid extraction occurrence profile'); END;
CREATE TRIGGER asset_extractions_no_conflicting_insert BEFORE INSERT ON asset_extractions
WHEN EXISTS (SELECT 1 FROM asset_extractions WHERE id = NEW.id OR rowid = NEW.rowid
  OR (asset_id = NEW.asset_id AND extraction_version = NEW.extraction_version)
  OR (asset_id = NEW.asset_id AND outcome = 'current' AND NEW.outcome = 'current')
  OR (NEW.recovery_operation_id IS NOT NULL AND recovery_operation_id = NEW.recovery_operation_id))
BEGIN SELECT RAISE(ABORT, 'extraction occurrence already exists'); END;

CREATE TRIGGER asset_recovery_operations_no_conflicting_insert BEFORE INSERT ON asset_recovery_operations
WHEN EXISTS (SELECT 1 FROM asset_recovery_operations WHERE id = NEW.id OR idempotency_key = NEW.idempotency_key
  OR (NEW.kind = 'text_retry' AND NEW.lifecycle = 'running' AND kind = 'text_retry'
    AND lifecycle = 'running' AND asset_id = NEW.asset_id))
BEGIN SELECT RAISE(ABORT, 'recovery operation already exists'); END;

CREATE TRIGGER asset_recovery_operations_frozen BEFORE UPDATE ON asset_recovery_operations
WHEN OLD.lifecycle <> 'running'
  OR NEW.id IS NOT OLD.id
  OR NEW.kind IS NOT OLD.kind
  OR NEW.asset_id IS NOT OLD.asset_id
  OR NEW.research_id IS NOT OLD.research_id
  OR NEW.expected_sha256 IS NOT OLD.expected_sha256
  OR NEW.expected_byte_size IS NOT OLD.expected_byte_size
  OR NEW.baseline_extraction_id IS NOT OLD.baseline_extraction_id
  OR NEW.baseline_profile IS NOT OLD.baseline_profile
  OR NEW.mode IS NOT OLD.mode
  OR NEW.idempotency_key IS NOT OLD.idempotency_key
  OR NEW.request_fingerprint IS NOT OLD.request_fingerprint
  OR NEW.created_at IS NOT OLD.created_at
  OR (NEW.lifecycle IS NOT OLD.lifecycle AND NEW.lifecycle NOT IN ('completed', 'interrupted'))
  OR (NEW.before_observation_id IS NOT OLD.before_observation_id AND NOT (
    OLD.kind = 'file_restore' AND OLD.before_observation_id IS NULL AND NEW.before_observation_id IS NOT NULL
    AND EXISTS (SELECT 1 FROM asset_file_observations WHERE id = NEW.before_observation_id
      AND operation_id = OLD.id AND kind = 'before_restore')))
  OR (NEW.after_observation_id IS NOT OLD.after_observation_id AND NOT (
    OLD.kind = 'file_restore' AND OLD.after_observation_id IS NULL AND NEW.after_observation_id IS NOT NULL
    AND EXISTS (SELECT 1 FROM asset_file_observations WHERE id = NEW.after_observation_id
      AND operation_id = OLD.id AND kind = 'after_restore')))
BEGIN SELECT RAISE(ABORT, 'recovery operation is frozen'); END;

DROP TRIGGER passages_no_update;
CREATE TRIGGER passages_no_update BEFORE UPDATE OF text, source_version_id, kind, physical_page, asset_id,
  printed_label, abstract_origin, payload_ref, extraction_version, text_sha256, text_source, retrieved_at, created_at ON passages
BEGIN SELECT RAISE(ABORT, 'passage content is immutable; create a new passage'); END;
