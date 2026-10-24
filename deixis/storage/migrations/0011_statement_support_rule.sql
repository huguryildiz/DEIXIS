-- Reverse citation search R4b (D108): the rule a statement check revision's results are presented by. A revision stored
-- before this migration reads with rule 1 (a work's class is its result, as it always looked); a new revision stores
-- rule 2 (a result counts as support only with at least one `stated` part, else `support_not_shown`). The stored
-- results, parts and quotes are never rewritten; the class is read from them (`domain.statement.support_class`).
ALTER TABLE statement_checks ADD COLUMN support_rule_version INTEGER NOT NULL DEFAULT 1
  CHECK (support_rule_version IN (1, 2));
