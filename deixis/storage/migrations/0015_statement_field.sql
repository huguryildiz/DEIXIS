-- The field a statement research's claim belongs to, as the person typed it (reverse citation search, R5): read by the
-- query model step and put first in the code query's setting block. NULL: none typed; the query model names one.
ALTER TABLE scope_revisions ADD COLUMN statement_field TEXT;
