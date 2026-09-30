ALTER TABLE table_columns ADD COLUMN lineage_role TEXT
  CHECK (lineage_role IN ('problem', 'change', 'uncertainty'));
CREATE UNIQUE INDEX table_columns_lineage_role ON table_columns (table_id, lineage_role)
  WHERE lineage_role IS NOT NULL AND removed_at IS NULL;
