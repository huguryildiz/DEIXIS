-- How a PDF passage's text was obtained (D51, D52): the PDF's own text layer, local OCR of a scanned page, or Marker's
-- reading of a page with mathematics. Existing passages came from the text layer. The equation reading of an extraction
-- (tool, version, pages read) is recorded with it.
ALTER TABLE passages ADD COLUMN text_source TEXT NOT NULL DEFAULT 'text_layer' CHECK (text_source IN ('text_layer', 'ocr', 'marker'));
ALTER TABLE asset_extractions ADD COLUMN math_json TEXT;
