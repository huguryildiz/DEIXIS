-- The answer model reads numbered display equations from page crops (D113). One row per request for one crop, kept like
-- Mathpix's (D40): reserved before sending, then answered, error or unknown (a timeout or lost connection after sending).
-- `model_revision` names connection, model, effort and a fingerprint prefix of the key (never the key), so a refused key
-- stops further requests until the key or the default model changes. `delivery_class` is the adapter's: a row whose call
-- never left (`before_send`) does not count against the budgets. An answer is reused for the same crop, connection,
-- model, effort and prompt version.
CREATE TABLE equation_model_requests (
  id TEXT PRIMARY KEY,
  crop_sha256 TEXT NOT NULL,
  asset_id TEXT NOT NULL,
  file_sha256 TEXT NOT NULL,
  page INTEGER NOT NULL,
  n TEXT NOT NULL,
  attempt INTEGER NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('reserved', 'answered', 'error', 'unknown')),
  connection TEXT NOT NULL,
  requested_model TEXT NOT NULL,
  resolved_model TEXT,
  reasoning_effort TEXT,
  prompt_version TEXT NOT NULL,
  model_revision TEXT NOT NULL,
  latex TEXT,
  http_status INTEGER,
  delivery_class TEXT,
  error_kind TEXT,
  reason TEXT,
  token_usage_json TEXT,
  reserved_at TEXT NOT NULL,
  answered_at TEXT
);

CREATE INDEX equation_model_requests_crop ON equation_model_requests(crop_sha256, status);

CREATE INDEX equation_model_requests_asset ON equation_model_requests(asset_id);

CREATE INDEX equation_model_requests_month ON equation_model_requests(reserved_at);
