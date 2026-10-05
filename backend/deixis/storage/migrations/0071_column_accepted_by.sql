-- A column the app added from the model's proposal without a person reviewing it (the study table that follows an answer).
-- NULL: a person added it. The value is recorded, never inferred.
ALTER TABLE table_columns ADD COLUMN accepted_by TEXT CHECK (accepted_by IS NULL OR accepted_by = 'automatic');
