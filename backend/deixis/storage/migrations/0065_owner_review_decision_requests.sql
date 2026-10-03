ALTER TABLE owner_review_decisions ADD COLUMN idempotency_key TEXT;
ALTER TABLE owner_review_decisions ADD COLUMN request_hash TEXT;
CREATE UNIQUE INDEX owner_review_decisions_request ON owner_review_decisions(idempotency_key);
DROP TRIGGER owner_review_decisions_no_conflicting_insert;
CREATE TRIGGER owner_review_decisions_no_conflicting_insert BEFORE INSERT ON owner_review_decisions
WHEN EXISTS (SELECT 1 FROM owner_review_decisions WHERE id = NEW.id
 OR (finding_id = NEW.finding_id AND ordinal = NEW.ordinal)
 OR idempotency_key = NEW.idempotency_key)
BEGIN SELECT RAISE(ABORT, 'owner_review_decisions already exists'); END;
