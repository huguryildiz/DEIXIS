-- One sw query is read page by page (slice 04c). NULL on every legacy row.
ALTER TABLE search_runs ADD COLUMN page_number INTEGER;   -- 0 for the first page
ALTER TABLE search_runs ADD COLUMN read_limit INTEGER;    -- SW_READ_LIMIT as it was when the page was read
ALTER TABLE search_runs ADD COLUMN read_total INTEGER;    -- records read for this query up to and including this page
ALTER TABLE search_runs ADD COLUMN stop_reason TEXT;      -- NULL while another page follows
ALTER TABLE search_runs ADD COLUMN unread_count INTEGER;  -- set with stop_reason; NULL when the provider gave no total
