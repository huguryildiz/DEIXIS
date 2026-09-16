-- The OCR reading of an extraction (D51): tool, version, languages, and pages read, with text, blank or failed.
ALTER TABLE asset_extractions ADD COLUMN ocr_json TEXT;
