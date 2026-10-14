-- The reasoning effort sent with each model call (D20): the value the adapter put in the request, null when
-- it sent none (no effort chosen, or a connection that never forwards one). Sessions stored before this file have null
-- too; a null effort is never filled in from the role's current setting or the model's default.
ALTER TABLE model_sessions ADD COLUMN reasoning_effort TEXT;
